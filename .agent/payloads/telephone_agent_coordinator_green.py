from pathlib import Path

ROOT = Path("app/src/main/java/pl/michalmatu/aicallbridge/session")
ROOT.mkdir(parents=True, exist_ok=True)

files = {
"CallMediaSessionState.java": r'''package pl.michalmatu.aicallbridge.session;

public enum CallMediaSessionState {
    IDLE,
    BINDING,
    PREPARING,
    ACTIVE,
    STOPPING,
    FAILED,
}
''',
"CallMediaSessionFailure.java": r'''package pl.michalmatu.aicallbridge.session;

public enum CallMediaSessionFailure {
    NONE,
    BIND_FAILED,
    PREPARE_FAILED,
    START_FAILED,
    HEARTBEAT_FAILED,
    HELPER_DISCONNECTED,
    INTERNAL_ERROR,
}
''',
"CallMediaSessionSnapshot.java": r'''package pl.michalmatu.aicallbridge.session;

/** Immutable structured state emitted by the production media-session coordinator. */
public record CallMediaSessionSnapshot(
    long generation,
    CallMediaSessionState state,
    CallMediaSessionFailure failure,
    String failureDetail,
    long startedAtMs,
    long updatedAtMs,
    long heartbeatCount
) {}
''',
"CallMediaEndpointLease.java": r'''package pl.michalmatu.aicallbridge.session;

/** App-owned lease for one transferred bidirectional media endpoint pair. */
public interface CallMediaEndpointLease extends AutoCloseable {
    @Override
    void close();
}
''',
"CallMediaSessionBackend.java": r'''package pl.michalmatu.aicallbridge.session;

/** Narrow backend seam keeping Shizuku/Binder details out of the lifecycle state machine. */
public interface CallMediaSessionBackend {
    interface BindCallback {
        void onBound(long generation);
        void onDisconnected(long generation);
    }

    void bind(long generation, BindCallback callback);
    void prepare(long generation, int sampleRateHz);
    CallMediaEndpointLease start(long generation);
    boolean heartbeat(long generation);
    void abort(long generation);
    void unbind(long generation);
}
''',
"CallMediaHeartbeatScheduler.java": r'''package pl.michalmatu.aicallbridge.session;

/** Schedules the app-side heartbeat refresh independently of model/network work. */
public interface CallMediaHeartbeatScheduler {
    AutoCloseable start(long generation, Runnable heartbeat);
}
''',
"CallMediaMonotonicClock.java": r'''package pl.michalmatu.aicallbridge.session;

@FunctionalInterface
public interface CallMediaMonotonicClock {
    long nowMs();
}
''',
"CallMediaSessionCoordinator.java": r'''package pl.michalmatu.aicallbridge.session;

import java.util.Objects;
import java.util.function.Consumer;

/**
 * Production app-side lifecycle owner for one privileged call-media generation.
 *
 * <p>This class deliberately contains no Samsung audio logic and no model/network logic. Those
 * remain behind the backend and later realtime seams. TAKE OVER closes the local endpoint lease
 * before asking the helper to abort.</p>
 */
public final class CallMediaSessionCoordinator implements AutoCloseable {
    private final CallMediaSessionBackend backend;
    private final CallMediaHeartbeatScheduler heartbeatScheduler;
    private final CallMediaMonotonicClock clock;
    private final Consumer<CallMediaSessionSnapshot> listener;

    private long generation;
    private CallMediaSessionState state = CallMediaSessionState.IDLE;
    private CallMediaSessionFailure failure = CallMediaSessionFailure.NONE;
    private String failureDetail;
    private long startedAtMs;
    private long updatedAtMs;
    private long heartbeatCount;
    private CallMediaEndpointLease endpointLease;
    private AutoCloseable heartbeatHandle;

    public CallMediaSessionCoordinator(
        CallMediaSessionBackend backend,
        CallMediaHeartbeatScheduler heartbeatScheduler,
        CallMediaMonotonicClock clock,
        Consumer<CallMediaSessionSnapshot> listener
    ) {
        this.backend = Objects.requireNonNull(backend, "backend");
        this.heartbeatScheduler = Objects.requireNonNull(heartbeatScheduler, "heartbeatScheduler");
        this.clock = Objects.requireNonNull(clock, "clock");
        this.listener = Objects.requireNonNull(listener, "listener");
        updatedAtMs = clock.nowMs();
        publishLocked();
    }

    public synchronized long start(int sampleRateHz) {
        if (sampleRateHz <= 0) {
            throw new IllegalArgumentException("sampleRateHz must be > 0");
        }
        if (state != CallMediaSessionState.IDLE) {
            throw new IllegalStateException("cannot start call media from " + state);
        }

        generation++;
        startedAtMs = clock.nowMs();
        updatedAtMs = startedAtMs;
        heartbeatCount = 0L;
        failure = CallMediaSessionFailure.NONE;
        failureDetail = null;
        state = CallMediaSessionState.BINDING;
        publishLocked();

        final long expectedGeneration = generation;
        try {
            backend.bind(expectedGeneration, new CallMediaSessionBackend.BindCallback() {
                @Override
                public void onBound(long callbackGeneration) {
                    handleBound(callbackGeneration, sampleRateHz);
                }

                @Override
                public void onDisconnected(long callbackGeneration) {
                    handleDisconnected(callbackGeneration);
                }
            });
        } catch (Throwable error) {
            failLocked(expectedGeneration, CallMediaSessionFailure.BIND_FAILED, error);
        }
        return expectedGeneration;
    }

    public synchronized CallMediaSessionSnapshot snapshot() {
        return snapshotLocked();
    }

    /**
     * Immediate human takeover path. Local endpoint ownership is released before Binder cleanup.
     */
    public synchronized void takeOverNow() {
        if (state == CallMediaSessionState.IDLE) {
            return;
        }
        if (state == CallMediaSessionState.STOPPING) {
            return;
        }

        final long expectedGeneration = generation;
        state = CallMediaSessionState.STOPPING;
        updatedAtMs = clock.nowMs();
        publishLocked();

        closeHeartbeatLocked();
        closeEndpointLocked();
        abortQuietly(expectedGeneration);
        unbindQuietly(expectedGeneration);

        state = CallMediaSessionState.IDLE;
        failure = CallMediaSessionFailure.NONE;
        failureDetail = null;
        updatedAtMs = clock.nowMs();
        publishLocked();
    }

    @Override
    public synchronized void close() {
        takeOverNow();
    }

    private synchronized void handleBound(long callbackGeneration, int sampleRateHz) {
        if (!isCurrent(callbackGeneration, CallMediaSessionState.BINDING)) {
            return;
        }

        state = CallMediaSessionState.PREPARING;
        updatedAtMs = clock.nowMs();
        publishLocked();

        try {
            backend.prepare(callbackGeneration, sampleRateHz);
        } catch (Throwable error) {
            failLocked(callbackGeneration, CallMediaSessionFailure.PREPARE_FAILED, error);
            return;
        }

        try {
            endpointLease = Objects.requireNonNull(
                backend.start(callbackGeneration),
                "backend.start returned null endpoint lease"
            );
        } catch (Throwable error) {
            failLocked(callbackGeneration, CallMediaSessionFailure.START_FAILED, error);
            return;
        }

        if (!isCurrent(callbackGeneration, CallMediaSessionState.PREPARING)) {
            closeEndpointLocked();
            return;
        }

        state = CallMediaSessionState.ACTIVE;
        updatedAtMs = clock.nowMs();
        publishLocked();

        try {
            heartbeatHandle = Objects.requireNonNull(
                heartbeatScheduler.start(
                    callbackGeneration,
                    () -> runHeartbeat(callbackGeneration)
                ),
                "heartbeat scheduler returned null handle"
            );
        } catch (Throwable error) {
            failLocked(callbackGeneration, CallMediaSessionFailure.INTERNAL_ERROR, error);
        }
    }

    private synchronized void handleDisconnected(long callbackGeneration) {
        if (callbackGeneration != generation) {
            return;
        }
        if (
            state == CallMediaSessionState.IDLE
                || state == CallMediaSessionState.STOPPING
                || state == CallMediaSessionState.FAILED
        ) {
            return;
        }
        failLocked(callbackGeneration, CallMediaSessionFailure.HELPER_DISCONNECTED, null);
    }

    private synchronized void runHeartbeat(long callbackGeneration) {
        if (!isCurrent(callbackGeneration, CallMediaSessionState.ACTIVE)) {
            return;
        }
        final boolean healthy;
        try {
            healthy = backend.heartbeat(callbackGeneration);
        } catch (Throwable error) {
            failLocked(callbackGeneration, CallMediaSessionFailure.HEARTBEAT_FAILED, error);
            return;
        }
        if (!healthy) {
            failLocked(callbackGeneration, CallMediaSessionFailure.HEARTBEAT_FAILED, null);
            return;
        }
        heartbeatCount++;
        updatedAtMs = clock.nowMs();
    }

    private void failLocked(
        long expectedGeneration,
        CallMediaSessionFailure reason,
        Throwable error
    ) {
        if (expectedGeneration != generation) {
            return;
        }
        if (state == CallMediaSessionState.IDLE || state == CallMediaSessionState.STOPPING) {
            return;
        }

        state = CallMediaSessionState.FAILED;
        failure = Objects.requireNonNull(reason, "reason");
        failureDetail = describe(error);
        updatedAtMs = clock.nowMs();

        closeHeartbeatLocked();
        closeEndpointLocked();
        abortQuietly(expectedGeneration);
        unbindQuietly(expectedGeneration);
        publishLocked();
    }

    private boolean isCurrent(long expectedGeneration, CallMediaSessionState expectedState) {
        return expectedGeneration == generation && state == expectedState;
    }

    private void closeHeartbeatLocked() {
        AutoCloseable handle = heartbeatHandle;
        heartbeatHandle = null;
        if (handle == null) {
            return;
        }
        try {
            handle.close();
        } catch (Throwable ignored) {
            // Cleanup remains fail closed through endpoint close + helper abort/watchdog.
        }
    }

    private void closeEndpointLocked() {
        CallMediaEndpointLease lease = endpointLease;
        endpointLease = null;
        if (lease == null) {
            return;
        }
        try {
            lease.close();
        } catch (Throwable ignored) {
            // Helper abort/watchdog remains an independent fail-safe.
        }
    }

    private void abortQuietly(long expectedGeneration) {
        try {
            backend.abort(expectedGeneration);
        } catch (Throwable ignored) {
            // Endpoint close + helper watchdog remain independent fail-safe paths.
        }
    }

    private void unbindQuietly(long expectedGeneration) {
        try {
            backend.unbind(expectedGeneration);
        } catch (Throwable ignored) {
            // Best-effort transport cleanup after local fail-safe action.
        }
    }

    private CallMediaSessionSnapshot snapshotLocked() {
        return new CallMediaSessionSnapshot(
            generation,
            state,
            failure,
            failureDetail,
            startedAtMs,
            updatedAtMs,
            heartbeatCount
        );
    }

    private void publishLocked() {
        listener.accept(snapshotLocked());
    }

    private static String describe(Throwable error) {
        if (error == null) {
            return null;
        }
        String message = error.getMessage();
        if (message == null || message.isBlank()) {
            return error.getClass().getSimpleName();
        }
        return error.getClass().getSimpleName()
            + ":"
            + message.replace('\n', ' ').replace('\r', ' ');
    }
}
'''
}

for name, content in files.items():
    (ROOT / name).write_text(content)
