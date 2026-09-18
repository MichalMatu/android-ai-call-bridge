from pathlib import Path

ROOT = Path("app/src/main/java/pl/michalmatu/aicallbridge/session")

(ROOT / "ShizukuCallMediaEndpointLease.java").write_text(r'''package pl.michalmatu.aicallbridge.session;

import android.os.ParcelFileDescriptor;

import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.atomic.AtomicBoolean;

/** Owns the two transferred PFD endpoints for one production media generation. */
public final class ShizukuCallMediaEndpointLease implements CallMediaEndpointLease {
    private final ParcelFileDescriptor.AutoCloseInputStream downlink;
    private final ParcelFileDescriptor.AutoCloseOutputStream uplink;
    private final AtomicBoolean closed = new AtomicBoolean(false);

    public ShizukuCallMediaEndpointLease(
        ParcelFileDescriptor downlinkReadEnd,
        ParcelFileDescriptor uplinkWriteEnd
    ) {
        this.downlink = new ParcelFileDescriptor.AutoCloseInputStream(downlinkReadEnd);
        this.uplink = new ParcelFileDescriptor.AutoCloseOutputStream(uplinkWriteEnd);
    }

    /** Future Realtime pump reads remote-party mono PCM16LE here. Do not close directly. */
    public InputStream downlink() {
        return downlink;
    }

    /** Future Realtime pump writes mono PCM16LE for CALL_ASSISTANT here. Do not close directly. */
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

(ROOT / "ScheduledCallMediaHeartbeatScheduler.java").write_text(r'''package pl.michalmatu.aicallbridge.session;

import java.util.Objects;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/** Production heartbeat scheduler. 500 ms stays comfortably inside the helper's 2 s watchdog. */
public final class ScheduledCallMediaHeartbeatScheduler
    implements CallMediaHeartbeatScheduler, AutoCloseable {

    public static final long HEARTBEAT_PERIOD_MS = 500L;

    private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor(
        runnable -> {
            Thread thread = new Thread(runnable, "aicall-media-heartbeat");
            thread.setDaemon(true);
            return thread;
        }
    );

    @Override
    public AutoCloseable start(long generation, Runnable heartbeat) {
        Objects.requireNonNull(heartbeat, "heartbeat");
        ScheduledFuture<?> future = executor.scheduleAtFixedRate(
            heartbeat,
            0L,
            HEARTBEAT_PERIOD_MS,
            TimeUnit.MILLISECONDS
        );
        return () -> future.cancel(false);
    }

    @Override
    public void close() {
        executor.shutdownNow();
    }
}
''')

(ROOT / "ShizukuCallMediaSessionBackend.java").write_text(r'''package pl.michalmatu.aicallbridge.session;

import android.content.ComponentName;
import android.content.Context;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;

import pl.michalmatu.aicallbridge.shizuku.IShizukuCallMediaService;
import pl.michalmatu.aicallbridge.shizuku.ShizukuCallMediaUserService;
import rikka.shizuku.Shizuku;

/** Production app-side Shizuku adapter for the frozen privileged call-media AIDL contract. */
public final class ShizukuCallMediaSessionBackend implements CallMediaSessionBackend {
    private final Shizuku.UserServiceArgs userServiceArgs;
    private Binding activeBinding;

    public ShizukuCallMediaSessionBackend(Context context) {
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

    @Override
    public synchronized void bind(long generation, BindCallback callback) {
        if (activeBinding != null) {
            throw new IllegalStateException("call-media UserService already bound");
        }
        if (!Shizuku.pingBinder() || Shizuku.isPreV11()) {
            throw new IllegalStateException("Shizuku binder is unavailable or unsupported");
        }
        if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
            throw new SecurityException("Shizuku permission is required");
        }

        Binding binding = new Binding(generation, callback);
        activeBinding = binding;
        try {
            Shizuku.bindUserService(userServiceArgs, binding);
        } catch (Throwable error) {
            activeBinding = null;
            throw asRuntime("failed to bind Shizuku call-media UserService", error);
        }
    }

    @Override
    public void prepare(long generation, int sampleRateHz) {
        serviceFor(generation).prepare(sampleRateHz);
    }

    @Override
    public CallMediaEndpointLease start(long generation) {
        IShizukuCallMediaService service = serviceFor(generation);
        ParcelFileDescriptor downlink = null;
        ParcelFileDescriptor uplink = null;
        try {
            service.startMedia();
            downlink = service.takeDownlinkReadEnd();
            uplink = service.takeUplinkWriteEnd();
            ShizukuCallMediaEndpointLease lease = new ShizukuCallMediaEndpointLease(
                downlink,
                uplink
            );
            downlink = null;
            uplink = null;
            return lease;
        } catch (Throwable error) {
            closeQuietly(downlink);
            closeQuietly(uplink);
            throw asRuntime("failed to start Shizuku call media", error);
        }
    }

    @Override
    public boolean heartbeat(long generation) {
        try {
            return serviceFor(generation).heartbeat();
        } catch (Throwable error) {
            throw asRuntime("Shizuku call-media heartbeat failed", error);
        }
    }

    @Override
    public void abort(long generation) {
        IShizukuCallMediaService service = serviceForOrNull(generation);
        if (service == null) {
            return;
        }
        try {
            service.abortNow();
        } catch (Throwable error) {
            throw asRuntime("Shizuku call-media abort failed", error);
        }
    }

    @Override
    public void unbind(long generation) {
        final Binding binding;
        synchronized (this) {
            if (activeBinding == null || activeBinding.generation != generation) {
                return;
            }
            binding = activeBinding;
            activeBinding = null;
        }
        binding.detachDeathRecipient();
        try {
            Shizuku.unbindUserService(userServiceArgs, binding, true);
        } catch (Throwable ignored) {
            // Endpoint close/helper watchdog already provide the local fail-safe boundary.
        }
    }

    private synchronized IShizukuCallMediaService serviceFor(long generation) {
        IShizukuCallMediaService service = serviceForOrNull(generation);
        if (service == null) {
            throw new IllegalStateException("call-media UserService is not connected for generation " + generation);
        }
        return service;
    }

    private synchronized IShizukuCallMediaService serviceForOrNull(long generation) {
        if (activeBinding == null || activeBinding.generation != generation) {
            return null;
        }
        return activeBinding.service;
    }

    private synchronized boolean isCurrent(Binding binding) {
        return activeBinding == binding;
    }

    private final class Binding implements ServiceConnection {
        final long generation;
        final BindCallback callback;
        IShizukuCallMediaService service;
        IBinder binder;
        IBinder.DeathRecipient deathRecipient;

        Binding(long generation, BindCallback callback) {
            this.generation = generation;
            this.callback = callback;
        }

        @Override
        public void onServiceConnected(ComponentName name, IBinder connectedBinder) {
            if (!isCurrent(this)) {
                return;
            }
            IShizukuCallMediaService connectedService =
                IShizukuCallMediaService.Stub.asInterface(connectedBinder);
            IBinder.DeathRecipient recipient = () -> {
                if (isCurrent(this)) {
                    callback.onDisconnected(generation);
                }
            };
            try {
                // App-side direct Binder death detection complements, not replaces, helper heartbeat.
                connectedBinder.linkToDeath(recipient, 0);
                synchronized (ShizukuCallMediaSessionBackend.this) {
                    if (!isCurrent(this)) {
                        connectedBinder.unlinkToDeath(recipient, 0);
                        return;
                    }
                    service = connectedService;
                    binder = connectedBinder;
                    deathRecipient = recipient;
                }
                callback.onBound(generation);
            } catch (Throwable error) {
                synchronized (ShizukuCallMediaSessionBackend.this) {
                    if (activeBinding == this) {
                        activeBinding = null;
                    }
                }
                throw asRuntime("failed to link Shizuku UserService death recipient", error);
            }
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            if (isCurrent(this)) {
                callback.onDisconnected(generation);
            }
        }

        void detachDeathRecipient() {
            IBinder currentBinder;
            IBinder.DeathRecipient currentRecipient;
            synchronized (ShizukuCallMediaSessionBackend.this) {
                currentBinder = binder;
                currentRecipient = deathRecipient;
                binder = null;
                deathRecipient = null;
                service = null;
            }
            if (currentBinder != null && currentRecipient != null) {
                try {
                    currentBinder.unlinkToDeath(currentRecipient, 0);
                } catch (Throwable ignored) {
                    // Binder may already be dead.
                }
            }
        }
    }

    private static RuntimeException asRuntime(String message, Throwable error) {
        if (error instanceof RuntimeException runtime) {
            return runtime;
        }
        return new IllegalStateException(message, error);
    }

    private static void closeQuietly(ParcelFileDescriptor descriptor) {
        if (descriptor == null) {
            return;
        }
        try {
            descriptor.close();
        } catch (Throwable ignored) {
            // Failed endpoint transfer cleanup.
        }
    }
}
''')

coordinator = ROOT / "CallMediaSessionCoordinator.java"
text = coordinator.read_text()
text = text.replace(
    "package pl.michalmatu.aicallbridge.session;\n\nimport java.util.Objects;",
    "package pl.michalmatu.aicallbridge.session;\n\nimport android.content.Context;\nimport android.os.SystemClock;\n\nimport java.util.Objects;",
    1,
)
text = text.replace(
    "    private final Consumer<CallMediaSessionSnapshot> listener;\n\n    private long generation;",
    "    private final Consumer<CallMediaSessionSnapshot> listener;\n    private AutoCloseable ownedRuntimeResource;\n    private boolean closed;\n\n    private long generation;",
    1,
)
needle = "    public CallMediaSessionCoordinator(\n        CallMediaSessionBackend backend,"
production_ctor = '''    public CallMediaSessionCoordinator(\n        Context context,\n        Consumer<CallMediaSessionSnapshot> listener\n    ) {\n        this(\n            new ShizukuCallMediaSessionBackend(context),\n            new ScheduledCallMediaHeartbeatScheduler(),\n            SystemClock::elapsedRealtime,\n            listener\n        );\n        ownedRuntimeResource = (AutoCloseable) heartbeatScheduler;\n    }\n\n'''
if needle not in text:
    raise SystemExit("coordinator constructor anchor missing")
text = text.replace(needle, production_ctor + needle, 1)
text = text.replace(
    "    public synchronized long start(int sampleRateHz) {\n        if (sampleRateHz <= 0) {",
    "    public synchronized long start(int sampleRateHz) {\n        if (closed) {\n            throw new IllegalStateException(\"coordinator is closed\");\n        }\n        if (sampleRateHz <= 0) {",
    1,
)
old_close = '''    @Override\n    public synchronized void close() {\n        takeOverNow();\n    }'''
new_close = '''    @Override\n    public synchronized void close() {\n        if (closed) {\n            return;\n        }\n        takeOverNow();\n        closed = true;\n        AutoCloseable resource = ownedRuntimeResource;\n        ownedRuntimeResource = null;\n        if (resource != null) {\n            try {\n                resource.close();\n            } catch (Throwable ignored) {\n                // Coordinator is already locally stopped.\n            }\n        }\n    }'''
if old_close not in text:
    raise SystemExit("coordinator close anchor missing")
text = text.replace(old_close, new_close, 1)
coordinator.write_text(text)
