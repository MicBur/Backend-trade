# Qt qmake Projektdatei für alternative Build-Variante (neben CMake)
# Nutzung: qmake && make / mingw32-make / nmake

QT += core quick
CONFIG += c++17 console
CONFIG -= app_bundle

TEMPLATE = app
TARGET = QtTradeFrontend

# Warnungen & striktere Flags (plattformabhängig etwas vereinfacht)
QMAKE_CXXFLAGS += -Wall -Wextra -Wpedantic

# Quellen
SOURCES += \
    src/main.cpp \
    src/redisclient.cpp \
    src/marketmodel.cpp \
    src/datapoller.cpp \
    src/portfoliomodel.cpp \
    src/ordersmodel.cpp \
    src/statusmodel.cpp \
    src/notificationsmodel.cpp

HEADERS += \
    src/redisclient.h \
    src/marketmodel.h \
    src/datapoller.h \
    src/portfoliomodel.h \
    src/ordersmodel.h \
    src/statusmodel.h \
    src/notificationsmodel.h \
    src/chartdatamodel.h \
    src/predictionsmodel.h

# Ressourcen (QML)
RESOURCES += qml.qrc

# hiredis Einbindung – Pfade anpassen falls nicht systemweit installiert
# Beispiel (Linux): QMAKE_INCDIR += /usr/include/hiredis
# Beispiel (Windows vcpkg): setze INCLUDE / LIB Pfade außerhalb oder nutze vcpkg integrate install
LIBS += -lhiredis

# Deployment Hinweis Windows:
# windeployqt QtTradeFrontend.exe

# Für MSVC stattdessen nmake verwenden, für MinGW mingw32-make.
