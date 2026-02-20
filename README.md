## INTRODUCTION

[![IRC Network](https://img.shields.io/badge/irc-freenode-blue.svg "IRC Freenode")](https://webchat.freenode.net/?channels=sddm)

SDDM is a modern display manager for X11 and Wayland sessions aiming to
be fast, simple and beautiful.
It uses modern technologies like QtQuick, which in turn gives the designer the ability to
create smooth, animated user interfaces.

SDDM is extremely themeable. We put no restrictions on the user interface design,
it is completely up to the designer. We simply provide a few callbacks to the user interface
which can be used for authentication, suspend etc.

To further ease theme creation we provide some premade components like a textbox,
a combox etc.

There are a few sample themes distributed with SDDM.
They can be used as a starting point for new themes.

## WAYLAND MULTI-SEAT ISOLATION (FORK FEATURE)

Standard SDDM often struggles with multi-seat Wayland due to resource collisions and a lack of process-level isolation for the greeter session. This fork introduces four core architectural changes to ensure stable, concurrent greeters.

### 1. D-Bus Session Isolation
To prevent session leaks and object collisions (such as the ObjectManager errors often seen in wireplumber), this patch moves D-Bus management into the SDDM daemon's native lifecycle.
* **Native Lifecycle Tracking:** Instead of relying on wrappers, the daemon utilizes `QProcess` to spawn a private dbus-daemon for each greeter.
* **Explicit Termination:** The daemon tracks the PID of the D-Bus process and explicitly sends SIGTERM when the greeter stops, ensuring no orphaned daemons or sockets remain between session transitions.

### 2. Deterministic Wayland Sockets
Multi-seat crashes often stem from lockfile collisions in `/run/user/<UID>/` (typically `wayland-0.lock`). This architecture enforces strict socket naming to ensure isolation.
* **Environment Injection:** The daemon injects a seat-specific `WAYLAND_DISPLAY` variable (e.g., `wayland-seat0`, `wayland-seat1`) into the environment of both the compositor and the greeter.
* **Socket Namespace:** By using deterministic names based on the `XDG_SEAT`, multiple greeters can run under the same sddm system user without attempting to acquire the same lockfile.

### 3. Native Compositor Socket Argument
Wayland compositors (like `kwin_wayland`) generally ignore the `WAYLAND_DISPLAY` environment variable when deciding which socket to create as a server.
* **The Bridge:** A patch in `src/helper/waylandhelper.cpp` natively reads the `WAYLAND_DISPLAY` variable from the helper's environment.
* **Native CLI Injection:** The helper dynamically appends `--socket <wayland-seatX>` to the compositor's command-line arguments upon launch. This ensures the server (KWin) creates the exact socket the client (SDDM Greeter) is configured to look for.

### 4. Hardware and Input Routing
The implementation relies on logind and the `XDG_SEAT` variable to handle hardware access.
* **DRM Isolation:** The compositor uses the injected `XDG_SEAT` to identify and claim the correct GPU DRM node.
* **Input Handling:** libinput utilizes the seat assignment to route keyboards, mice, and touchscreens to the correct greeter instance, preventing cross-seat input leakage.

### Configuration (`sddm.conf`)

To enable the Wayland greeter with multi-seat support, you need to configure `sddm.conf` (usually located at `/etc/sddm.conf` or `/etc/sddm.conf.d/`).

You must set the display server to `wayland` in the `[General]` section and provide the appropriate Wayland compositor command in the `[Wayland]` section.

Example configuration:

```ini
[General]
# Set the display server to wayland
DisplayServer=wayland

[Wayland]
# Path to the Wayland compositor to execute when starting the greeter
CompositorCommand=kwin_wayland --drm --no-lockscreen --no-global-shortcuts --locale1

# Optional: Map seats to specific DRM devices if logind routing needs overriding
# SeatDrmOverride=seat0=/dev/dri/card0,seat1=/dev/dri/card1
```

## SCREENSHOTS

![sample screenshot](https://raw.github.com/sddm/sddm/master/src/greeter/theme/maui.jpg)

## VIDEOS

* [Video background](https://www.youtube.com/watch?v=kKwz2FQcE3c)
* [Maui theme 1](https://www.youtube.com/watch?v=-0d1wkcU9DU)
* [Maui theme 2](https://www.youtube.com/watch?v=dJ28mrOeuNA)

## RESOURCES

* [Issue tracker](https://github.com/sddm/sddm/issues)
* [Wiki](https://github.com/sddm/sddm/wiki)
* [Mailing List](https://groups.google.com/group/sddm-devel)
* IRC channel `#sddm` on [chat.freenode.net](https://webchat.freenode.net?channels=sddm)

## INSTALLATION

Qt >= 5.15.0 is required to use SDDM.

SDDM runs the greeter as a system user named "sddm" whose home directory needs
to be set to `/var/lib/sddm`.

If pam and systemd are available, the greeter will go through logind
which will give it access to drm devices.

Distributions without pam and systemd will need to put the "sddm" user
into the "video" group, otherwise errors regarding GL and drm devices
might be experienced.

## VIRTUAL TERMINALS

SDDM is assumed to start at the tty specified by the cmake variable
SDDM_INITIAL_VT which is an integer and defaults to 1.

If SDDM_INITIAL_VT wasn't available, SDDM will use the next available one
instead.

You can override SDDM_INITIAL_VT if you want to have a different one if,
for example, you were planning on using tty1 for something else.

## LICENSE

Source code of SDDM is licensed under GNU GPL version 2 or later (at your choosing).
QML files are MIT licensed and images are CC BY 3.0.

## TROUBLESHOOTING

### NVIDIA Prime

Add this at the bottom of the Xsetup script:

```sh
if [ -e /sbin/prime-offload ]; then
    echo running NVIDIA Prime setup /sbin/prime-offload, you will need to manually run /sbin/prime-switch to shut down
    /sbin/prime-offload
fi
```

### No User Icon

SDDM reads user icon from either ~/.face.icon or FacesDir/username.face.icon

You need to make sure that SDDM user have permissions to read those files.
In case you don't want to allow other users to access your $HOME you can use
ACLs if your filesystem does support it.

```sh
setfacl -m u:sddm:x /home/username
setfacl -m u:sddm:r /home/username/.face.icon
```

### Custom DPI

In order to set custom DPI for high resolution screens you should configure
Xorg yourself.  An easy way is to pass an additional argument to Xorg.

Edit ``/etc/sddm.conf``, go to the ``X11`` section and change ``ServerArguments`` like this:

```
ServerArguments=-nolisten tcp -dpi 192
```

to set DPI to 192.

As an alternative you can edit Xorg configuration ``xorg.conf``, please refer to the
Xorg documentation.
