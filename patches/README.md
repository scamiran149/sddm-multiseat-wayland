# How it Works: SDDM Wayland Multi-seat Isolation

Standard SDDM often struggles with multi-seat Wayland due to resource collisions and a lack of process-level isolation for the greeter session. This implementation introduces four core architectural changes to ensure stable, concurrent greeters.

## 1. D-Bus Session Isolation
To prevent session leaks and object collisions (such as the ObjectManager errors often seen in wireplumber), this patch moves D-Bus management into the SDDM daemon's native lifecycle.

* **Native Lifecycle Tracking:** Instead of relying on wrappers, the daemon utilizes `QProcess` to spawn a private dbus-daemon for each greeter.
* **Explicit Termination:** The daemon tracks the PID of the D-Bus process and explicitly sends SIGTERM when the greeter stops, ensuring no orphaned daemons or sockets remain between session transitions.

## 2. Deterministic Wayland Sockets
Multi-seat crashes often stem from lockfile collisions in `/run/user/<UID>/` (typically `wayland-0.lock`). This architecture enforces strict socket naming to ensure isolation.

* **Environment Injection:** The daemon injects a seat-specific `WAYLAND_DISPLAY` variable (e.g., `wayland-seat0`, `wayland-seat1`) into the environment of both the compositor and the greeter.
* **Socket Namespace:** By using deterministic names based on the `XDG_SEAT`, multiple greeters can run under the same sddm system user without attempting to acquire the same lockfile.

## 3. Native Compositor Socket Argument
Wayland compositors (like `kwin_wayland`) generally ignore the `WAYLAND_DISPLAY` environment variable when deciding which socket to create as a server.

* **The Bridge:** A patch in `src/helper/waylandhelper.cpp` natively reads the `WAYLAND_DISPLAY` variable from the helper's environment.
* **Native CLI Injection:** The helper dynamically appends `--socket <wayland-seatX>` to the compositor's command-line arguments upon launch. This ensures the server (KWin) creates the exact socket the client (SDDM Greeter) is configured to look for.

## 4. Hardware and Input Routing
The implementation relies on logind and the `XDG_SEAT` variable to handle hardware access.

* **DRM Isolation:** The compositor uses the injected `XDG_SEAT` to identify and claim the correct GPU DRM node.
* **Input Handling:** libinput utilizes the seat assignment to route keyboards, mice, and touchscreens to the correct greeter instance, preventing cross-seat input leakage.
