from pathlib import Path


def write(path: str, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


write("docs/superpowers/plans/2026-09-18-telephone-agent-v1.md", r'''# Telephone Agent v1 implementation plan

Date: 2026-09-18

## Goal

Build a production call agent above the frozen Samsung/Shizuku media path. The diagnostic probes remain regression tools; they are not the production lifecycle owner.

Target flow:

```text
user intent
  -> task + explicit constraints
  -> target/business resolution
  -> READY_TO_DIAL
  -> cellular call
  -> production call-media session
  -> Realtime conversation engine
  -> negotiation within authorized constraints
  -> structured outcome
  -> optional external action such as Calendar
```

## Frozen boundary

Do not change the proven Phase 2D Samsung audio primitives without concrete regression evidence. In particular preserve attribution, CALL_ASSISTANT/TELEPHONY_TX, mono PCM16LE inside the bridge, PFD ownership, shared fail-safe lifetime, endpoint-loss cleanup, helper heartbeat, `CallModeWatchdog`, and local TAKE OVER.

## Current OpenAI API findings

Verified against current official OpenAI documentation on 2026-09-18:

- Realtime supports audio/text over WebSocket, WebRTC or SIP;
- Realtime supports function calling, which is suitable for orchestration handoffs/tool decisions;
- short-lived client secrets can be created through the Realtime client-secrets API;
- model choice must remain configuration, not a hardcoded architectural dependency;
- the phone APK must never contain a long-lived OpenAI API key.

For this project, WebSocket is the preferred first transport because cellular media is already available as explicit PCM PFD streams. WebRTC would add another media stack without removing the need to bridge the cellular PCM endpoints. Keep `RealtimeTransport` as the seam so transport choice can change later.

Do not assume the model-side PCM rate equals the frozen Samsung 16 kHz rate. The helper stays at its proven 16 kHz PCM16LE boundary; if the selected Realtime session format differs, resample only in the normal-app/realtime adapter.

## Slice 1 — production media lifecycle core

Implement:

- `CallMediaSessionStateMachine` with `IDLE/BINDING/PREPARING/ACTIVE/STOPPING/FAILED`;
- monotonically increasing generation id so stale callbacks cannot resurrect old sessions;
- structured failure reason and immutable snapshot;
- app-side `ShizukuCallMediaBackend` using the existing proven AIDL contract;
- direct `IBinder.linkToDeath` handling in the normal app;
- production `CallMediaSessionCoordinator` owning:
  - bind;
  - prepare/start;
  - transferred PFD streams;
  - 500 ms heartbeats against the helper's 2 s fail-safe;
  - local synchronous endpoint close for TAKE OVER;
  - helper abort/unbind cleanup;
  - structured telemetry events.

TAKE OVER closes local PFD endpoints synchronously before waiting on Binder, network or model work. This is intentional: endpoint loss is already physically proven to stop the whole helper generation.

## Slice 2 — user task/workflow model

Add immutable task data for:
- target description;
- action;
- service;
- date/time constraints;
- price constraint;
- NFZ/private/insurance constraint;
- authorized user facts.

Add workflow states:

```text
RESEARCHING
READY_TO_DIAL
DIALING
ACTIVE_NEGOTIATION
NEEDS_USER_DECISION
COMPLETED
FAILED
```

Only material choices outside explicit constraints may enter `NEEDS_USER_DECISION`.

## Slice 3 — Realtime transport adapter

Implement behind `RealtimeTransport`:
- server-mediated/short-lived credentials;
- authenticated WebSocket lifecycle;
- explicit configured audio format;
- PCM frame batching and bounded queues;
- model output -> uplink writer;
- downlink reader -> model input;
- barge-in/cancel response;
- transport failure -> coordinator stop/fail-closed;
- no persistent recording.

Keep orchestration outcome/tool calls outside the raw audio pump.

## Slice 4 — resolver and dialing orchestration

Add a target resolver interface and a dialer interface before connecting public business lookup. Resolution must return source/identity metadata and fail closed on ambiguous targets. The product workflow, not the Realtime transport, decides whether to dial.

## Tests

- exhaustive lifecycle transition/generation tests;
- failure and restart tests;
- workflow transition/constraint validation tests;
- backend/coordinator host tests where Android-free seams permit them;
- full existing Python suite and Gradle suite after each production slice;
- no new physical call unless a change touches the frozen Samsung path or a real device-only invariant.
''')

write("app/src/main/java/pl/michalmatu/aicallbridge/call/CallMediaSessionStateMachine.java", r'''package pl.michalmatu.aicallbridge.call;

import java.util.Objects;

/** Pure lifecycle state for one app-side call-media generation. */
public final class CallMediaSessionStateMachine {
    public enum State {
        IDLE,
        BINDING,
        PREPARING,
        ACTIVE,
        STOPPING,
        FAILED,
    }

    public enum FailureReason {
        NONE,
        SHIZUKU_UNAVAILABLE,
        SHIZUKU_PERMISSION_REQUIRED,
        BIND_FAILED,
        BINDER_DIED,
        PREPARE_FAILED,
        START_FAILED,
        ENDPOINT_TRANSFER_FAILED,
        HEARTBEAT_LOST,
        SERVICE_DISCONNECTED,
        INTERNAL_ERROR,
    }

    public static final class Snapshot {
        public final long generation;
        public final State state;
        public final FailureReason failureReason;
        public final String failureDetail;

        private Snapshot(
            long generation,
            State state,
            FailureReason failureReason,
            String failureDetail
        ) {
            this.generation = generation;
            this.state = Objects.requireNonNull(state, "state");
            this.failureReason = Objects.requireNonNull(failureReason, "failureReason");
            this.failureDetail = failureDetail;
        }
    }

    private long generation;
    private State state = State.IDLE;
    private FailureReason failureReason = FailureReason.NONE;
    private String failureDetail;

    public synchronized long begin() {
        if (state != State.IDLE && state != State.FAILED) {
            throw new IllegalStateException("cannot begin from " + state);
        }
        generation++;
        state = State.BINDING;
        failureReason = FailureReason.NONE;
        failureDetail = null;
        return generation;
    }

    public synchronized boolean markPreparing(long expectedGeneration) {
        return transition(expectedGeneration, State.BINDING, State.PREPARING);
    }

    public synchronized boolean markActive(long expectedGeneration) {
        return transition(expectedGeneration, State.PREPARING, State.ACTIVE);
    }

    public synchronized boolean beginStopping(long expectedGeneration) {
        if (expectedGeneration != generation || state == State.IDLE) {
            return false;
        }
        if (state == State.STOPPING) {
            return true;
        }
        state = State.STOPPING;
        return true;
    }

    public synchronized boolean markIdle(long expectedGeneration) {
        if (expectedGeneration != generation || state != State.STOPPING) {
            return false;
        }
        state = State.IDLE;
        failureReason = FailureReason.NONE;
        failureDetail = null;
        return true;
    }

    public synchronized boolean fail(
        long expectedGeneration,
        FailureReason reason,
        String detail
    ) {
        Objects.requireNonNull(reason, "reason");
        if (reason == FailureReason.NONE) {
            throw new IllegalArgumentException("failure reason must not be NONE");
        }
        if (expectedGeneration != generation || state == State.IDLE || state == State.STOPPING) {
            return false;
        }
        state = State.FAILED;
        failureReason = reason;
        failureDetail = detail;
        return true;
    }

    public synchronized boolean isCurrent(long expectedGeneration) {
        return expectedGeneration == generation;
    }

    public synchronized Snapshot snapshot() {
        return new Snapshot(generation, state, failureReason, failureDetail);
    }

    private boolean transition(long expectedGeneration, State from, State to) {
        if (expectedGeneration != generation || state != from) {
            return false;
        }
        state = to;
        return true;
    }
}
''')

write("app/src/main/java/pl/michalmatu/aicallbridge/call/CallMediaStreams.java", r'''package pl.michalmatu.aicallbridge.call;

import android.os.ParcelFileDescriptor;

import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * App-owned stream view of the two transferred call-media PFDs.
 *
 * <p>The coordinator retains close ownership. Consumers may read/write but must not close these
 * streams themselves.</p>
 */
public final class CallMediaStreams implements AutoCloseable {
    private final ParcelFileDescriptor.AutoCloseInputStream downlink;
    private final ParcelFileDescriptor.AutoCloseOutputStream uplink;
    private final AtomicBoolean closed = new AtomicBoolean(false);

    public CallMediaStreams(
        ParcelFileDescriptor downlinkReadEnd,
        ParcelFileDescriptor uplinkWriteEnd
    ) {
        this.downlink = new ParcelFileDescriptor.AutoCloseInputStream(downlinkReadEnd);
        this.uplink = new ParcelFileDescriptor.AutoCloseOutputStream(uplinkWriteEnd);
    }

    public InputStream downlink() {
        return downlink;
    }

    public OutputStream uplink() {
        return uplink;
    }

    public boolean isClosed() {
        return closed.get();
    }

    @Override
    public void close() {
        if (!closed.compareAndSet(false, true)) {
            return;
        }
        try {
            downlink.close();
        } catch (Throwable ignored) {
            // Local fail-safe cleanup.
        }
        try {
            uplink.close();
        } catch (Throwable ignored) {
            // Local fail-safe cleanup.
        }
    }
}
''')

write("app/src/main/java/pl/michalmatu/aicallbridge/call/ShizukuCallMediaBackend.java", r'''package pl.michalmatu.aicallbridge.call;

import android.content.ComponentName;
import android.content.Context;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;

import pl.michalmatu.aicallbridge.call.CallMediaSessionStateMachine.FailureReason;
import pl.michalmatu.aicallbridge.shizuku.IShizukuCallMediaService;
import pl.michalmatu.aicallbridge.shizuku.ShizukuCallMediaUserService;
import rikka.shizuku.Shizuku;

/** App-side binding seam for the proven Shizuku call-media UserService. */
public final class ShizukuCallMediaBackend {
    public interface Callback {
        void onConnected(Connection connection);
        void onFailure(FailureReason reason, Throwable error);
        void onBinderDied();
        void onDisconnected();
    }

    public static final class Connection {
        private final IShizukuCallMediaService service;

        private Connection(IShizukuCallMediaService service) {
            this.service = service;
        }

        public void prepare(int sampleRate) throws Exception {
            service.prepare(sampleRate);
        }

        public void startMedia() throws Exception {
            service.startMedia();
        }

        public CallMediaStreams takeStreams() throws Exception {
            ParcelFileDescriptor downlink = null;
            ParcelFileDescriptor uplink = null;
            try {
                downlink = service.takeDownlinkReadEnd();
                uplink = service.takeUplinkWriteEnd();
                CallMediaStreams result = new CallMediaStreams(downlink, uplink);
                downlink = null;
                uplink = null;
                return result;
            } finally {
                closeQuietly(downlink);
                closeQuietly(uplink);
            }
        }

        public boolean heartbeat() throws Exception {
            return service.heartbeat();
        }

        public void abortNow() throws Exception {
            service.abortNow();
        }
    }

    private final Shizuku.UserServiceArgs userServiceArgs;
    private Callback callback;
    private IBinder binder;
    private IBinder.DeathRecipient deathRecipient;
    private boolean bound;

    private final ServiceConnection serviceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder connectedBinder) {
            Callback current = callback;
            if (current == null) {
                return;
            }
            IShizukuCallMediaService service = IShizukuCallMediaService.Stub.asInterface(connectedBinder);
            IBinder.DeathRecipient recipient = () -> {
                Callback active = callback;
                if (active != null) {
                    active.onBinderDied();
                }
            };
            try {
                connectedBinder.linkToDeath(recipient, 0);
                binder = connectedBinder;
                deathRecipient = recipient;
                current.onConnected(new Connection(service));
            } catch (Throwable error) {
                current.onFailure(FailureReason.BIND_FAILED, error);
            }
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            Callback current = callback;
            if (current != null) {
                current.onDisconnected();
            }
        }
    };

    public ShizukuCallMediaBackend(Context context) {
        Context appContext = context.getApplicationContext();
        userServiceArgs = new Shizuku.UserServiceArgs(
            new ComponentName(appContext, ShizukuCallMediaUserService.class)
        )
            .daemon(false)
            .processNameSuffix("call_media")
            .tag("call-media-v1")
            .version(1)
            .debuggable(false);
    }

    public synchronized void bind(Callback newCallback) {
        if (bound) {
            throw new IllegalStateException("call-media UserService is already bound");
        }
        callback = newCallback;
        if (!Shizuku.pingBinder() || Shizuku.isPreV11()) {
            newCallback.onFailure(FailureReason.SHIZUKU_UNAVAILABLE, null);
            return;
        }
        if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
            newCallback.onFailure(FailureReason.SHIZUKU_PERMISSION_REQUIRED, null);
            return;
        }
        try {
            bound = true;
            Shizuku.bindUserService(userServiceArgs, serviceConnection);
        } catch (Throwable error) {
            bound = false;
            newCallback.onFailure(FailureReason.BIND_FAILED, error);
        }
    }

    public synchronized void unbind() {
        unlinkDeathRecipient();
        callback = null;
        if (!bound) {
            return;
        }
        bound = false;
        try {
            Shizuku.unbindUserService(userServiceArgs, serviceConnection, true);
        } catch (Throwable ignored) {
            // Local endpoint close and helper watchdog remain the fail-safe boundary.
        }
    }

    private void unlinkDeathRecipient() {
        IBinder currentBinder = binder;
        IBinder.DeathRecipient currentRecipient = deathRecipient;
        binder = null;
        deathRecipient = null;
        if (currentBinder == null || currentRecipient == null) {
            return;
        }
        try {
            currentBinder.unlinkToDeath(currentRecipient, 0);
        } catch (Throwable ignored) {
            // Binder may already be dead.
        }
    }

    private static void closeQuietly(ParcelFileDescriptor descriptor) {
        if (descriptor == null) {
            return;
        }
        try {
            descriptor.close();
        } catch (Throwable ignored) {
            // Failed transfer cleanup.
        }
    }
}
''')

write("app/src/main/java/pl/michalmatu/aicallbridge/call/CallMediaSessionCoordinator.java", r'''package pl.michalmatu.aicallbridge.call;

import android.content.Context;
import android.os.SystemClock;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import pl.michalmatu.aicallbridge.call.CallMediaSessionStateMachine.FailureReason;
import pl.michalmatu.aicallbridge.call.CallMediaSessionStateMachine.Snapshot;
import pl.michalmatu.aicallbridge.call.CallMediaSessionStateMachine.State;

/** Production app-side owner for one Shizuku call-media session. */
public final class CallMediaSessionCoordinator {
    public interface Listener {
        void onTelemetry(TelemetryEvent event);
        void onMediaReady(CallMediaStreams streams, Snapshot snapshot);
    }

    public static final class TelemetryEvent {
        public final long sequence;
        public final long elapsedRealtimeMs;
        public final String event;
        public final Snapshot snapshot;
        public final String detail;

        private TelemetryEvent(
            long sequence,
            long elapsedRealtimeMs,
            String event,
            Snapshot snapshot,
            String detail
        ) {
            this.sequence = sequence;
            this.elapsedRealtimeMs = elapsedRealtimeMs;
            this.event = event;
            this.snapshot = snapshot;
            this.detail = detail;
        }
    }

    private static final int SAMPLE_RATE = 16_000;
    private static final long HEARTBEAT_PERIOD_MS = 500L;

    private final Object lock = new Object();
    private final CallMediaSessionStateMachine lifecycle = new CallMediaSessionStateMachine();
    private final ShizukuCallMediaBackend backend;
    private final ScheduledExecutorService worker;
    private final AtomicLong telemetrySequence = new AtomicLong();
    private final Listener listener;

    private ShizukuCallMediaBackend.Connection connection;
    private CallMediaStreams streams;
    private ScheduledFuture<?> heartbeatTask;

    public CallMediaSessionCoordinator(Context context, Listener listener) {
        this(
            new ShizukuCallMediaBackend(context),
            Executors.newSingleThreadScheduledExecutor(runnable -> {
                Thread thread = new Thread(runnable, "aicall-media-coordinator");
                thread.setDaemon(true);
                return thread;
            }),
            listener
        );
    }

    CallMediaSessionCoordinator(
        ShizukuCallMediaBackend backend,
        ScheduledExecutorService worker,
        Listener listener
    ) {
        this.backend = backend;
        this.worker = worker;
        this.listener = listener;
    }

    public Snapshot snapshot() {
        return lifecycle.snapshot();
    }

    public long start() {
        final long generation;
        synchronized (lock) {
            generation = lifecycle.begin();
        }
        emit("binding", null);
        backend.bind(new ShizukuCallMediaBackend.Callback() {
            @Override
            public void onConnected(ShizukuCallMediaBackend.Connection connected) {
                handleConnected(generation, connected);
            }

            @Override
            public void onFailure(FailureReason reason, Throwable error) {
                fail(generation, reason, error);
            }

            @Override
            public void onBinderDied() {
                fail(generation, FailureReason.BINDER_DIED, null);
            }

            @Override
            public void onDisconnected() {
                Snapshot current = lifecycle.snapshot();
                if (current.generation == generation && current.state != State.STOPPING && current.state != State.IDLE) {
                    fail(generation, FailureReason.SERVICE_DISCONNECTED, null);
                }
            }
        });
        return generation;
    }

    /**
     * Immediate human takeover. Local PFDs are closed synchronously before any Binder cleanup.
     */
    public void takeOver() {
        final long generation;
        final ShizukuCallMediaBackend.Connection toAbort;
        final CallMediaStreams toClose;
        synchronized (lock) {
            Snapshot current = lifecycle.snapshot();
            if (current.state == State.IDLE || current.state == State.STOPPING) {
                return;
            }
            generation = current.generation;
            lifecycle.beginStopping(generation);
            cancelHeartbeatLocked();
            toAbort = connection;
            connection = null;
            toClose = streams;
            streams = null;
        }

        // This is the primary local TAKE OVER action. Endpoint loss is physically proven to
        // terminate the helper generation even if Binder/model/network cleanup is delayed.
        closeQuietly(toClose);
        emit("stopping", "take_over");

        worker.execute(() -> {
            abortQuietly(toAbort);
            backend.unbind();
            synchronized (lock) {
                lifecycle.markIdle(generation);
            }
            emit("idle", "take_over_complete");
        });
    }

    private void handleConnected(
        long generation,
        ShizukuCallMediaBackend.Connection connected
    ) {
        synchronized (lock) {
            Snapshot current = lifecycle.snapshot();
            if (current.generation != generation || current.state != State.BINDING) {
                abortQuietly(connected);
                backend.unbind();
                return;
            }
            connection = connected;
            lifecycle.markPreparing(generation);
        }
        emit("preparing", null);

        worker.execute(() -> {
            try {
                if (!isPreparing(generation)) {
                    return;
                }
                connected.prepare(SAMPLE_RATE);
                if (!isPreparing(generation)) {
                    abortQuietly(connected);
                    return;
                }
                connected.startMedia();
                CallMediaStreams acquired;
                try {
                    acquired = connected.takeStreams();
                } catch (Throwable error) {
                    fail(generation, FailureReason.ENDPOINT_TRANSFER_FAILED, error);
                    return;
                }

                Snapshot activeSnapshot;
                synchronized (lock) {
                    Snapshot current = lifecycle.snapshot();
                    if (current.generation != generation || current.state != State.PREPARING) {
                        closeQuietly(acquired);
                        abortQuietly(connected);
                        return;
                    }
                    streams = acquired;
                    lifecycle.markActive(generation);
                    activeSnapshot = lifecycle.snapshot();
                    heartbeatTask = worker.scheduleAtFixedRate(
                        () -> heartbeat(generation, connected),
                        HEARTBEAT_PERIOD_MS,
                        HEARTBEAT_PERIOD_MS,
                        TimeUnit.MILLISECONDS
                    );
                }
                emit("active", null);
                if (listener != null) {
                    listener.onMediaReady(acquired, activeSnapshot);
                }
            } catch (Throwable error) {
                FailureReason reason = connected == connection
                    ? FailureReason.START_FAILED
                    : FailureReason.INTERNAL_ERROR;
                fail(generation, reason, error);
            }
        });
    }

    private boolean isPreparing(long generation) {
        Snapshot current = lifecycle.snapshot();
        return current.generation == generation && current.state == State.PREPARING;
    }

    private void heartbeat(long generation, ShizukuCallMediaBackend.Connection expected) {
        Snapshot current = lifecycle.snapshot();
        if (current.generation != generation || current.state != State.ACTIVE) {
            return;
        }
        try {
            if (!expected.heartbeat()) {
                fail(generation, FailureReason.HEARTBEAT_LOST, null);
            }
        } catch (Throwable error) {
            fail(generation, FailureReason.HEARTBEAT_LOST, error);
        }
    }

    private void fail(long generation, FailureReason reason, Throwable error) {
        final CallMediaStreams toClose;
        final ShizukuCallMediaBackend.Connection toAbort;
        final String detail = describe(error);
        synchronized (lock) {
            if (!lifecycle.fail(generation, reason, detail)) {
                return;
            }
            cancelHeartbeatLocked();
            toClose = streams;
            streams = null;
            toAbort = connection;
            connection = null;
        }
        closeQuietly(toClose);
        emit("failed", detail);
        worker.execute(() -> {
            abortQuietly(toAbort);
            backend.unbind();
        });
    }

    private void cancelHeartbeatLocked() {
        if (heartbeatTask != null) {
            heartbeatTask.cancel(false);
            heartbeatTask = null;
        }
    }

    private void emit(String event, String detail) {
        if (listener == null) {
            return;
        }
        listener.onTelemetry(
            new TelemetryEvent(
                telemetrySequence.incrementAndGet(),
                SystemClock.elapsedRealtime(),
                event,
                lifecycle.snapshot(),
                detail
            )
        );
    }

    private static void closeQuietly(CallMediaStreams value) {
        if (value == null) {
            return;
        }
        try {
            value.close();
        } catch (Throwable ignored) {
            // Local fail-safe cleanup.
        }
    }

    private static void abortQuietly(ShizukuCallMediaBackend.Connection value) {
        if (value == null) {
            return;
        }
        try {
            value.abortNow();
        } catch (Throwable ignored) {
            // PFD close + helper watchdog remain independent fail-safe paths.
        }
    }

    private static String describe(Throwable error) {
        if (error == null) {
            return null;
        }
        String message = error.getMessage();
        if (message == null || message.isBlank()) {
            return error.getClass().getSimpleName();
        }
        return error.getClass().getSimpleName() + ":" + message.replace('\n', ' ').replace('\r', ' ');
    }
}
''')

write("app/src/main/kotlin/pl/michalmatu/aicallbridge/agent/TelephoneTask.kt", r'''package pl.michalmatu.aicallbridge.agent

import java.time.Instant
import java.time.LocalTime

enum class PaymentConstraint {
    ANY,
    NFZ,
    PRIVATE,
    INSURANCE,
}

data class TelephoneTask(
    val id: String,
    val targetDescription: String,
    val action: String,
    val service: String? = null,
    val earliest: Instant? = null,
    val latest: Instant? = null,
    val preferredAfter: LocalTime? = null,
    val maxPriceMinor: Long? = null,
    val currency: String = "PLN",
    val paymentConstraint: PaymentConstraint = PaymentConstraint.ANY,
    val insuranceProvider: String? = null,
    val authorizedUserFacts: Map<String, String> = emptyMap(),
) {
    init {
        require(id.isNotBlank()) { "id must not be blank" }
        require(targetDescription.isNotBlank()) { "targetDescription must not be blank" }
        require(action.isNotBlank()) { "action must not be blank" }
        require(maxPriceMinor == null || maxPriceMinor >= 0) { "maxPriceMinor must be >= 0" }
        require(earliest == null || latest == null || !latest.isBefore(earliest)) {
            "latest must not be before earliest"
        }
        require(paymentConstraint != PaymentConstraint.INSURANCE || !insuranceProvider.isNullOrBlank()) {
            "insuranceProvider is required for INSURANCE"
        }
    }
}

data class ResolvedCallTarget(
    val displayName: String,
    val phoneNumber: String,
    val source: String,
) {
    init {
        require(displayName.isNotBlank()) { "displayName must not be blank" }
        require(phoneNumber.isNotBlank()) { "phoneNumber must not be blank" }
        require(source.isNotBlank()) { "source must not be blank" }
    }
}

enum class CallOutcomeStatus {
    COMPLETED,
    NO_MATCH,
    NEEDS_USER_DECISION,
    FAILED,
}

data class TelephoneCallOutcome(
    val status: CallOutcomeStatus,
    val summary: String,
    val appointmentTime: Instant? = null,
    val priceMinor: Long? = null,
    val currency: String? = null,
    val confirmationReference: String? = null,
    val decisionQuestion: String? = null,
)
''')

write("app/src/main/kotlin/pl/michalmatu/aicallbridge/agent/TelephoneWorkflowStateMachine.kt", r'''package pl.michalmatu.aicallbridge.agent

enum class CallWorkflowState {
    RESEARCHING,
    READY_TO_DIAL,
    DIALING,
    ACTIVE_NEGOTIATION,
    NEEDS_USER_DECISION,
    COMPLETED,
    FAILED,
}

class TelephoneWorkflowStateMachine(
    val task: TelephoneTask,
) {
    var state: CallWorkflowState = CallWorkflowState.RESEARCHING
        private set

    var target: ResolvedCallTarget? = null
        private set

    var outcome: TelephoneCallOutcome? = null
        private set

    fun targetResolved(resolved: ResolvedCallTarget) {
        requireState(CallWorkflowState.RESEARCHING)
        target = resolved
        state = CallWorkflowState.READY_TO_DIAL
    }

    fun dialStarted() {
        requireState(CallWorkflowState.READY_TO_DIAL)
        state = CallWorkflowState.DIALING
    }

    fun negotiationStarted() {
        requireState(CallWorkflowState.DIALING)
        state = CallWorkflowState.ACTIVE_NEGOTIATION
    }

    fun needsUserDecision(question: String) {
        requireState(CallWorkflowState.ACTIVE_NEGOTIATION)
        require(question.isNotBlank()) { "question must not be blank" }
        outcome = TelephoneCallOutcome(
            status = CallOutcomeStatus.NEEDS_USER_DECISION,
            summary = "Material decision required",
            decisionQuestion = question,
        )
        state = CallWorkflowState.NEEDS_USER_DECISION
    }

    fun resumeNegotiation() {
        requireState(CallWorkflowState.NEEDS_USER_DECISION)
        outcome = null
        state = CallWorkflowState.ACTIVE_NEGOTIATION
    }

    fun complete(result: TelephoneCallOutcome) {
        require(state == CallWorkflowState.ACTIVE_NEGOTIATION || state == CallWorkflowState.NEEDS_USER_DECISION) {
            "cannot complete from $state"
        }
        require(result.status == CallOutcomeStatus.COMPLETED || result.status == CallOutcomeStatus.NO_MATCH) {
            "terminal success outcome must be COMPLETED or NO_MATCH"
        }
        outcome = result
        state = CallWorkflowState.COMPLETED
    }

    fun fail(summary: String) {
        require(state != CallWorkflowState.COMPLETED && state != CallWorkflowState.FAILED) {
            "cannot fail from $state"
        }
        require(summary.isNotBlank()) { "summary must not be blank" }
        outcome = TelephoneCallOutcome(CallOutcomeStatus.FAILED, summary)
        state = CallWorkflowState.FAILED
    }

    private fun requireState(expected: CallWorkflowState) {
        check(state == expected) { "expected $expected, was $state" }
    }
}
''')

write("app/src/test/java/pl/michalmatu/aicallbridge/call/CallMediaSessionStateMachineTest.java", r'''package pl.michalmatu.aicallbridge.call;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import pl.michalmatu.aicallbridge.call.CallMediaSessionStateMachine.FailureReason;
import pl.michalmatu.aicallbridge.call.CallMediaSessionStateMachine.State;

public final class CallMediaSessionStateMachineTest {
    @Test
    public void happyPathIsExplicitAndReturnsToIdle() {
        CallMediaSessionStateMachine machine = new CallMediaSessionStateMachine();
        long generation = machine.begin();

        assertEquals(State.BINDING, machine.snapshot().state);
        assertTrue(machine.markPreparing(generation));
        assertTrue(machine.markActive(generation));
        assertTrue(machine.beginStopping(generation));
        assertTrue(machine.markIdle(generation));

        assertEquals(State.IDLE, machine.snapshot().state);
        assertEquals(FailureReason.NONE, machine.snapshot().failureReason);
        assertNull(machine.snapshot().failureDetail);
    }

    @Test
    public void staleGenerationCannotAdvanceNewSession() {
        CallMediaSessionStateMachine machine = new CallMediaSessionStateMachine();
        long first = machine.begin();
        assertTrue(machine.fail(first, FailureReason.BINDER_DIED, "dead"));
        long second = machine.begin();

        assertFalse(machine.markPreparing(first));
        assertEquals(second, machine.snapshot().generation);
        assertEquals(State.BINDING, machine.snapshot().state);
    }

    @Test
    public void failureIsStructuredAndRestartClearsIt() {
        CallMediaSessionStateMachine machine = new CallMediaSessionStateMachine();
        long first = machine.begin();
        assertTrue(machine.fail(first, FailureReason.HEARTBEAT_LOST, "timeout"));

        assertEquals(State.FAILED, machine.snapshot().state);
        assertEquals(FailureReason.HEARTBEAT_LOST, machine.snapshot().failureReason);
        assertEquals("timeout", machine.snapshot().failureDetail);

        long second = machine.begin();
        assertTrue(second > first);
        assertEquals(FailureReason.NONE, machine.snapshot().failureReason);
        assertNull(machine.snapshot().failureDetail);
    }

    @Test(expected = IllegalStateException.class)
    public void duplicateBeginIsRejected() {
        CallMediaSessionStateMachine machine = new CallMediaSessionStateMachine();
        machine.begin();
        machine.begin();
    }
}
''')

write("app/src/test/kotlin/pl/michalmatu/aicallbridge/agent/TelephoneWorkflowStateMachineTest.kt", r'''package pl.michalmatu.aicallbridge.agent

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TelephoneWorkflowStateMachineTest {
    @Test
    fun happyPathReachesStructuredCompletion() {
        val task = TelephoneTask(
            id = "task-1",
            targetDescription = "dermatology clinic in Sky Tower",
            action = "book appointment",
            service = "dermatologist",
        )
        val workflow = TelephoneWorkflowStateMachine(task)

        workflow.targetResolved(ResolvedCallTarget("Clinic", "+48123456789", "resolver"))
        workflow.dialStarted()
        workflow.negotiationStarted()
        workflow.complete(
            TelephoneCallOutcome(
                status = CallOutcomeStatus.COMPLETED,
                summary = "Booked",
                appointmentTime = Instant.parse("2026-09-23T15:30:00Z"),
            ),
        )

        assertEquals(CallWorkflowState.COMPLETED, workflow.state)
        assertEquals(CallOutcomeStatus.COMPLETED, workflow.outcome?.status)
    }

    @Test
    fun materialDecisionCanPauseAndResumeNegotiation() {
        val workflow = TelephoneWorkflowStateMachine(
            TelephoneTask("task-2", "clinic", "book"),
        )
        workflow.targetResolved(ResolvedCallTarget("Clinic", "123456789", "resolver"))
        workflow.dialStarted()
        workflow.negotiationStarted()
        workflow.needsUserDecision("Only a materially more expensive slot is available. Accept?")

        assertEquals(CallWorkflowState.NEEDS_USER_DECISION, workflow.state)
        assertEquals(CallOutcomeStatus.NEEDS_USER_DECISION, workflow.outcome?.status)

        workflow.resumeNegotiation()
        assertEquals(CallWorkflowState.ACTIVE_NEGOTIATION, workflow.state)
        assertNull(workflow.outcome)
    }

    @Test(expected = IllegalArgumentException::class)
    fun insuranceRequiresProvider() {
        TelephoneTask(
            id = "task-3",
            targetDescription = "clinic",
            action = "book",
            paymentConstraint = PaymentConstraint.INSURANCE,
        )
    }
}
''')
