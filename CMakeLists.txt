cmake_minimum_required(VERSION 3.21)
project(QtTradeFrontend VERSION 0.6.0 LANGUAGES CXX)

# QML Language Server Konfig (Editor Autocomplete / weniger Warnungen)
set(QT_QML_GENERATE_QMLLS_INI ON)

# Qt Meta-Objekt / Ressourcen automatische Generierung aktivieren
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Qt
find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Core Quick)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core Quick)

# hiredis Einbindung: bevorzugt lokale Source (Unterordner hiredis-1.3.0) sonst Stub
set(HIREDIS_SRC_DIR ${CMAKE_SOURCE_DIR}/hiredis-1.3.0)
if(EXISTS ${HIREDIS_SRC_DIR}/CMakeLists.txt)
    message(STATUS "Using bundled hiredis at ${HIREDIS_SRC_DIR}")
    # Unterprojekt hinzufügen (erzeugt Ziel hiredis)
    add_subdirectory(${HIREDIS_SRC_DIR} EXCLUDE_FROM_ALL)
    # Markiere für Code, dass wir die vendored Struktur (flat header) nutzen
    add_compile_definitions(HIREDIS_VENDORED)
    set(HIREDIS_AVAILABLE TRUE)
else()
    message(WARNING "Bundled hiredis not found - falling back to stub (no live Redis connectivity)")
    add_compile_definitions(REDIS_STUB)
    set(HIREDIS_AVAILABLE FALSE)
endif()

set(SOURCES
    src/main.cpp
    src/redisclient.cpp
    src/marketmodel.cpp
    src/datapoller.cpp
    src/portfoliomodel.cpp
    src/ordersmodel.cpp
    src/notificationsmodel.cpp
    src/statusmodel.cpp
)

set(HEADERS
    src/redisclient.h
    src/marketmodel.h
    src/datapoller.h
    src/portfoliomodel.h
    src/ordersmodel.h
    src/statusmodel.h
    src/notificationsmodel.h
    src/chartdatamodel.h
    src/predictionsmodel.h
)

qt_add_executable(QtTradeFrontend
    ${SOURCES}
    ${HEADERS}
)

# Version Header generieren
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/version.in.h ${CMAKE_CURRENT_BINARY_DIR}/generated/version.h @ONLY)
target_include_directories(QtTradeFrontend PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/generated)

qt_add_qml_module(QtTradeFrontend
    URI Frontend
    VERSION 1.0
    QML_FILES
        qml/MainSimple.qml
        qml/MainStep1.qml
        qml/MainStep2.qml
        qml/MainStep3.qml
        qml/Main.qml
        qml/Theme.qml
        qml/components/HeaderBar.qml
        qml/components/SideNav.qml
        qml/components/MarketList.qml
        qml/components/StatusBadge.qml
        qml/components/CandleChart.qml
)

# --- kleines Testprogramm für Redis Ping ---
add_executable(redis_ping_test
    src/redisclient.cpp
    src/redisclient.h
    src/redis_ping_main.cpp
)
target_compile_definitions(redis_ping_test PRIVATE QT_NO_KEYWORDS)
if(HIREDIS_AVAILABLE)
    if(TARGET hiredis)
        target_link_libraries(redis_ping_test PRIVATE hiredis)
    elseif(TARGET libhiredis)
        target_link_libraries(redis_ping_test PRIVATE libhiredis)
    endif()
endif()
target_link_libraries(redis_ping_test PRIVATE Qt::Core)
add_custom_command(TARGET redis_ping_test POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo "Usage: set REDIS_HOST / REDIS_PORT (default 127.0.0.1:6380)"
)

target_link_libraries(QtTradeFrontend PRIVATE Qt::Core Qt::Quick)

if(HIREDIS_AVAILABLE)
    # hiredis installiert sein: includes liegen im Unterprojekt (es exportiert target hiredis (static/shared je nach default))
    # Manche Versionen definieren Zielnamen hiredis oder libhiredis. Prüfen und verlinken was existiert.
    if(TARGET hiredis)
        target_link_libraries(QtTradeFrontend PRIVATE hiredis)
    elseif(TARGET libhiredis)
        target_link_libraries(QtTradeFrontend PRIVATE libhiredis)
    else()
        message(WARNING "hiredis target not found after add_subdirectory - enabling stub")
        target_compile_definitions(QtTradeFrontend PRIVATE REDIS_STUB)
    endif()
endif()

# Windows: deploy steps comment (use windeployqt after build)

install(TARGETS QtTradeFrontend
    BUNDLE DESTINATION .
    RUNTIME DESTINATION bin
)
