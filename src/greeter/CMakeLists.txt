if(QT_MAJOR_VERSION EQUAL "5")
    # Keep the unversioned name for Qt5. When upgrading SDDM, the old daemon
    # might still be running and only know about "sddm-greeter". Keeping the
    # previous name around also helps users calling it directly.
    set(GREETER_TARGET sddm-greeter)
else()
    set(GREETER_TARGET sddm-greeter-qt${QT_MAJOR_VERSION})
endif()

message(STATUS "Building greeter for Qt ${QT_MAJOR_VERSION} as ${GREETER_TARGET}")

include_directories(
    "${CMAKE_SOURCE_DIR}/src/common"
    "${CMAKE_BINARY_DIR}/src/common"
    "${LIBXCB_INCLUDE_DIR}"
)

set(GREETER_SOURCES
    ${CMAKE_SOURCE_DIR}/src/common/Configuration.cpp
    ${CMAKE_SOURCE_DIR}/src/common/ConfigReader.cpp
    ${CMAKE_SOURCE_DIR}/src/common/Session.cpp
    ${CMAKE_SOURCE_DIR}/src/common/SignalHandler.cpp
    ${CMAKE_SOURCE_DIR}/src/common/SocketWriter.cpp
    ${CMAKE_SOURCE_DIR}/src/common/ThemeConfig.cpp
    ${CMAKE_SOURCE_DIR}/src/common/ThemeMetadata.cpp
    GreeterApp.cpp
    GreeterProxy.cpp
    IdleController.cpp
    IdleController.h
    Login1IdleHint.cpp
    Login1IdleHint.h
    DpmsManager.cpp
    DpmsManager.h
    KWinDpmsBackend.cpp
    KWinDpmsBackend.h
    KeyboardLayout.cpp
    KeyboardModel.cpp
    ScreenModel.cpp
    SessionModel.cpp
    UserModel.cpp
    waylandkeyboardbackend.cpp
    waylandkeyboardbackend.h
    XcbKeyboardBackend.cpp
)

configure_file("theme.qrc" "theme.qrc")
configure_file("theme/metadata.desktop.in" "theme/metadata.desktop" @ONLY)

qt_add_resources(RESOURCES ${CMAKE_CURRENT_BINARY_DIR}/theme.qrc)

add_executable(${GREETER_TARGET} ${GREETER_SOURCES} ${RESOURCES})

# Generate Wayland protocol client sources for kde-dpms (Qt6 only)
if(QT_MAJOR_VERSION EQUAL 6)
    find_package(WaylandScanner REQUIRED)
    find_package(Qt6 COMPONENTS WaylandClient REQUIRED)
    qt6_generate_wayland_protocol_client_sources(${GREETER_TARGET}
        FILES ${CMAKE_CURRENT_SOURCE_DIR}/protocols/dpms.xml
    )
    target_link_libraries(${GREETER_TARGET} Qt6::WaylandClient Wayland::Client)
endif()

target_link_libraries(${GREETER_TARGET}
                      Qt${QT_MAJOR_VERSION}::Quick
                      Qt${QT_MAJOR_VERSION}::DBus
                      ${LIBXCB_LIBRARIES}
                      ${LIBXKB_LIBRARIES})

if(JOURNALD_FOUND)
    target_link_libraries(${GREETER_TARGET} ${JOURNALD_LIBRARIES})
endif()

# Translations
add_dependencies(${GREETER_TARGET} components-translation themes-translation)

install(TARGETS ${GREETER_TARGET} DESTINATION "${CMAKE_INSTALL_BINDIR}")