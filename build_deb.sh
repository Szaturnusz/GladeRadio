#!/bin/bash

APP_NAME="gladeradio"
VERSION="1.0.0"
ARCH="all"
BUILD_DIR="build/${APP_NAME}_${VERSION}_${ARCH}"

# Takarítás
rm -rf build
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/share/${APP_NAME}"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/512x512/apps"

# Méret kiszámítása (KB-ban)
INSTALLED_SIZE=$(du -ks "${BUILD_DIR}/usr" | cut -f1)

# Control fájl létrehozása
cat <<EOF > "${BUILD_DIR}/DEBIAN/control"
Package: ${APP_NAME}
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Depends: python3, python3-gi, python3-requests, python3-pil, gir1.2-gtk-3.0, gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, gstreamer1.0-libav
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Szaturnusz <szaturnusz@localhost>
Homepage: https://github.com/szaturnusz/GladeRadio
Description: GladeRádió - Modern Online Rádió Lejátszó
 Gyors, könnyű és modern rádió lejátszó több ezer adóval.
 Támogatja a kedvenceket, keresést és ország szerinti szűrést.
 Ez a csomag telepíti a GladeRádió alkalmazást és minden szükséges függőségét.
EOF

# Indító script (wrapper)
cat <<EOF > "${BUILD_DIR}/usr/bin/${APP_NAME}"
#!/bin/bash
cd /usr/share/${APP_NAME}
exec python3 main.py "\$@"
EOF
chmod +x "${BUILD_DIR}/usr/bin/${APP_NAME}"

# Desktop fájl
cat <<EOF > "${BUILD_DIR}/usr/share/applications/${APP_NAME}.desktop"
[Desktop Entry]
Name=GladeRádió
Comment=Hallgass online rádiókat
Exec=${APP_NAME}
Icon=${APP_NAME}
Terminal=false
Type=Application
Categories=Audio;AudioVideo;Player;
Keywords=radio;music;stream;
EOF

# Fájlok másolása
cp main.py "${BUILD_DIR}/usr/share/${APP_NAME}/"

# Ikon kezelése
if [ -f "Glade.png" ]; then
    echo "Glade.png megtalálva, másolás..."
    cp "Glade.png" "${BUILD_DIR}/usr/share/${APP_NAME}/Glade.png"
    cp "Glade.png" "${BUILD_DIR}/usr/share/icons/hicolor/512x512/apps/${APP_NAME}.png"
elif [ -f "app_icon.png" ]; then
    echo "Glade.png nem található, app_icon.png használata..."
    cp "app_icon.png" "${BUILD_DIR}/usr/share/${APP_NAME}/Glade.png"
    cp "app_icon.png" "${BUILD_DIR}/usr/share/icons/hicolor/512x512/apps/${APP_NAME}.png"
else
    echo "Nincs ikon fájl! Letöltés..."
    wget -O "${BUILD_DIR}/usr/share/${APP_NAME}/Glade.png" "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Circle-icons-radio.svg/512px-Circle-icons-radio.svg.png"
    cp "${BUILD_DIR}/usr/share/${APP_NAME}/Glade.png" "${BUILD_DIR}/usr/share/icons/hicolor/512x512/apps/${APP_NAME}.png"
fi

# Jogosultságok beállítása
chmod 755 "${BUILD_DIR}/DEBIAN/control"
chmod -R 755 "${BUILD_DIR}/usr"

# Post-install script (ikon cache frissítés)
cat <<EOF > "${BUILD_DIR}/DEBIAN/postinst"
#!/bin/bash
set -e
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor
fi
if [ -x /usr/bin/update-desktop-database ]; then
    update-desktop-database /usr/share/applications
fi
EOF
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# Post-remove script (takarítás)
cat <<EOF > "${BUILD_DIR}/DEBIAN/postrm"
#!/bin/bash
set -e
if [ "\$1" = "purge" ] || [ "\$1" = "remove" ]; then
    rm -rf /usr/share/${APP_NAME}
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor
fi
if [ -x /usr/bin/update-desktop-database ]; then
    update-desktop-database /usr/share/applications
fi
EOF
chmod 755 "${BUILD_DIR}/DEBIAN/postrm"

# Csomagolás
dpkg-deb --build "${BUILD_DIR}"

echo "Kész! A telepítő csomag: build/${APP_NAME}_${VERSION}_${ARCH}.deb"
