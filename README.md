# 📻 GladeRádió

**Modern, gyors és könnyű online rádió- és tévélejátszó Linux rendszerekre.**

A GladeRádió egy Python és GTK3 alapú alkalmazás, amely a [Radio Browser](https://www.radio-browser.info/) közösségi adatbázisát használja, így több mint **100.000 rádióadóhoz** és számos **TV csatornához** biztosít hozzáférést.

## ✨ Főbb funkciók

*   🌍 **Hatalmas választék:** Több mint 100.000 rádióadó a világ minden tájáról.
*   📺 **Élő TV támogatás:** TV csatornák nézése külön, átméretezhető ablakban (HLS/.m3u8 támogatás).
*   ⭐ **Kedvencek:** Mentsd el a legjobb adókat, hogy később egy kattintással elérd őket.
*   🔍 **Okos keresés:** Keress név, címke vagy ország szerint.
*   🎨 **Modern felület:** Szemkímélő sötét téma, reszponzív elrendezés és albumborító megjelenítés.
*   🚀 **Gyors:** Hatékony gyorsítótárazás és aszinkron betöltés.

## 📥 Telepítés

### Debian / Ubuntu / Linux Mint (.deb)

Töltsd le a legújabb telepítőt a [Releases](https://github.com/szaturnusz/GladeRadio/releases) oldalról, majd telepítsd:

```bash
sudo dpkg -i gladeradio_1.0.0_all.deb
sudo apt-get install -f  # Ha hiányzó függőségek lennének
```

### Fejlesztői telepítés (Forráskódból)

Ha fejleszteni szeretnéd vagy forrásból futtatni:

1.  **Függőségek telepítése:**
    ```bash
    sudo apt install python3-gi python3-requests python3-pil gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav
    ```

2.  **Klónozás és futtatás:**
    ```bash
    git clone https://github.com/szaturnusz/GladeRadio.git
    cd GladeRadio
    python3 main.py
    ```

## 🛠️ Technológia

*   **Nyelv:** Python 3
*   **GUI:** GTK+ 3.0 (PyGObject)
*   **Média:** GStreamer 1.0 (Playbin, HLS support)
*   **Adatbázis:** Radio Browser API

## 📝 Licenc

Ez a projekt nyílt forráskódú. Használd egészséggel!
