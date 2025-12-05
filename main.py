import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gst', '1.0')
try:
    gi.require_version('GstVideo', '1.0')
except:
    pass
from gi.repository import Gtk, Gst, Gdk, GLib, GdkPixbuf, Pango
try:
    from gi.repository import GstVideo
except:
    GstVideo = None

import requests
import threading
import json
import os
import bz2
import io
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

# Alkalmazás nevének beállítása (hogy ne main.py legyen az ablak címe)
GLib.set_prgname("gladeradio")
GLib.set_application_name("GladeRádió")

# GStreamer debug üzenetek letiltása
os.environ['GST_DEBUG'] = '0'

class ScrollingLabel(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__()
        # EXTERNAL policy: elrejti a görgetősávot, de engedi a görgetést
        self.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.set_shadow_type(Gtk.ShadowType.NONE)
        
        try:
            self.set_propagate_natural_width(False)
            self.set_propagate_natural_height(True)
        except:
            pass
            
        self.set_size_request(150, -1)
        
        self.label = Gtk.Label(xalign=0)
        self.label.set_single_line_mode(True) # Fontos: egysoros mód
        self.add(self.label)
        
        self.h_adj = self.get_hadjustment()
        self.scroll_pos = 0
        self.direction = 1
        self.wait_counter = 0
        self.timer_id = GLib.timeout_add(50, self._tick)
        self.connect("destroy", self.on_destroy)

    def on_destroy(self, widget):
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

    def set_markup(self, text):
        self.label.set_markup(text)
        self.reset()

    def set_text(self, text):
        self.label.set_text(text)
        self.reset()
        
    def reset(self):
        self.scroll_pos = 0
        self.direction = 1
        self.wait_counter = 60
        self.h_adj.set_value(0)

    def _tick(self):
        if not self.timer_id: return False
        
        upper = self.h_adj.get_upper()
        page_size = self.h_adj.get_page_size()
        max_scroll = upper - page_size
        
        if max_scroll <= 0:
            return True
            
        if self.wait_counter > 0:
            self.wait_counter -= 1
            return True
            
        self.scroll_pos += self.direction
        
        if self.scroll_pos >= max_scroll:
            self.scroll_pos = max_scroll
            self.direction = -1
            self.wait_counter = 60
        elif self.scroll_pos <= 0:
            self.scroll_pos = 0
            self.direction = 1
            self.wait_counter = 60
            
        self.h_adj.set_value(self.scroll_pos)
        return True

class RadioApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Pro Radio Player")
        
        # Ablak alapbeállítások
        self.set_default_size(1000, 700)
        self.set_border_width(0)
        self.set_position(Gtk.WindowPosition.CENTER)
        
        # App Ikon
        self.setup_icon()
        
        # Stílus betöltése
        self.setup_css()
        
        # Adatok inicializálása
        self.radios = []
        self.filtered_radios = []
        self.current_radio = None
        self.favorites = set()
        self.displayed_count = 50
        self.load_favorites()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # GStreamer setup
        Gst.init(None)
        self.player = Gst.ElementFactory.make("playbin", "player")
        self.player.connect("source-setup", self.on_source_setup)
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission() # Fontos a videó ablakhoz
        bus.connect("message::tag", self.on_tag_message)
        bus.connect("message::error", self.on_player_error)
        bus.connect("sync-message::element", self.on_sync_message)

        # Videó ablak előkészítése (TV csatornákhoz)
        self.video_window = Gtk.Window(title="ÉlőTv")
        self.video_window.set_title("ÉlőTv")
        try:
            self.video_window.set_wmclass("gladeradio-tv", "GladeRadio")
        except:
            pass
            
        self.video_window.set_default_size(800, 450)
        self.video_window.connect("delete-event", self.on_video_window_close)
        self.video_area = Gtk.DrawingArea()
        self.video_area.set_double_buffered(False)
        self.video_window.add(self.video_area)
        
        # Fontos: a widgetnek láthatónak kell lennie (flag), hogy legyen ablaka
        self.video_area.show()
        
        # Realize kell, hogy legyen XID
        self.video_window.realize()
        self.video_area.realize()
        
        window = self.video_area.get_window()
        if window:
            self.video_xid = window.get_xid()
        else:
            print("Hiba: Nem sikerült lekérni az XID-t a videóhoz")
            self.video_xid = None

        # Fő elrendezés felépítése
        self.setup_ui()
        
        # Adatok betöltése háttérszálon, hogy ne fagyjon le az UI
        threading.Thread(target=self.load_radios_bg, daemon=True).start()

    def setup_icon(self):
        # Ikon keresése: először a Glade.png, aztán app_icon.png, végül letöltés
        possible_icons = ["Glade.png", "app_icon.png"]
        icon_path = None
        
        # Abszolút útvonal meghatározása (hogy telepítve is megtalálja)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        for icon_name in possible_icons:
            full_path = os.path.join(base_dir, icon_name)
            if os.path.exists(full_path):
                icon_path = full_path
                break
        
        # Ha nincs meg az ikon, letöltjük (fallback) a config mappába
        if not icon_path:
            try:
                config_dir = self.get_config_dir()
                fallback_path = os.path.join(config_dir, "app_icon.png")
                
                # Ha már letöltöttük korábban
                if os.path.exists(fallback_path):
                    icon_path = fallback_path
                else:
                    url = "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Circle-icons-radio.svg/512px-Circle-icons-radio.svg.png"
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        with open(fallback_path, "wb") as f:
                            f.write(resp.content)
                        icon_path = fallback_path
            except:
                pass
        
        # Beállítás
        if icon_path and os.path.exists(icon_path):
            try:
                self.set_icon_from_file(icon_path)
            except:
                self.set_icon_name("audio-x-generic")
        else:
            self.set_icon_name("audio-x-generic")

    def setup_css(self):
        css_provider = Gtk.CssProvider()
        css = """
        window {
            background-color: #242424;
            color: #ffffff;
        }
        headerbar {
            background-color: #333333;
            border-bottom: 1px solid #1a1a1a;
        }
        .sidebar {
            background-color: #2a2a2a;
            border-right: 1px solid #1a1a1a;
        }
        list {
            background-color: #2a2a2a;
        }
        .sidebar-row {
            padding: 10px;
            border-bottom: 1px solid #333333;
            background-color: #2a2a2a;
            color: #ffffff;
        }
        .sidebar-row:hover {
            background-color: #333333;
        }
        .sidebar-row:selected {
            background-color: #3daee9;
            color: white;
        }
        .radio-card {
            background-color: #333333;
            border-radius: 8px;
            padding: 10px;
            margin: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3);
            transition: all 200ms ease;
        }
        .radio-card:hover {
            background-color: #444444;
        }
        .player-bar {
            background-color: #1a1a1a;
            padding: 10px;
            border-top: 1px solid #333333;
        }
        entry {
            background-color: #444444;
            color: white;
            border: none;
            border-radius: 4px;
        }
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def setup_ui(self):
        # HeaderBar (Címsor)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("Pro Radio Player")
        header.set_subtitle("Online Rádió Böngésző")
        self.set_titlebar(header)

        # Kereső a fejlécben
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Keresés...")
        self.search_entry.set_width_chars(30)
        self.search_entry.connect("search-changed", self.on_search_changed)
        header.pack_start(self.search_entry)

        # Frissítés gomb
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_btn.connect("clicked", lambda x: threading.Thread(target=self.load_radios_bg, daemon=True).start())
        header.pack_end(refresh_btn)

        # Fő konténer (Vertikális: Tartalom + Lejátszó)
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(main_box)

        # Tartalom (Paned: Oldalsáv + Rádió Lista)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(250) # Oldalsáv szélessége
        main_box.pack_start(paned, True, True, 0)

        # --- Oldalsáv (Bal oldal) ---
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.get_style_context().add_class("sidebar")
        
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.connect("row-selected", self.on_category_selected)
        sidebar_scroll.add(self.sidebar_list)
        
        # Kategóriák hozzáadása (kezdetben csak a fixek)
        self.populate_sidebar()
        
        paned.pack1(sidebar_scroll, False, False)

        # --- Rádió Lista (Jobb oldal) ---
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Info sáv
        self.status_label = Gtk.Label(label="Betöltés...", xalign=0)
        self.status_label.set_margin_start(10)
        self.status_label.set_margin_top(5)
        self.status_label.set_margin_bottom(5)
        content_box.pack_start(self.status_label, False, False, 0)

        # ScrolledWindow a FlowBox-nak
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_box.pack_start(self.scrolled_window, True, True, 0)

        # FlowBox a kártyáknak
        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(10) # Dinamikus, de limitált
        self.flowbox.set_min_children_per_line(1)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(False) # Fontos a méretezéshez
        self.flowbox.set_column_spacing(10)
        self.flowbox.set_row_spacing(10)
        self.flowbox.set_margin_top(10)
        self.flowbox.set_margin_bottom(10)
        self.flowbox.set_margin_start(10)
        self.flowbox.set_margin_end(10)
        
        self.scrolled_window.add(self.flowbox)
        
        # "Több betöltése" gomb a lista aljára (trükkös FlowBox-nál, inkább a Box aljára)
        self.load_more_btn = Gtk.Button(label="Több betöltése")
        self.load_more_btn.connect("clicked", self.on_load_more)
        self.load_more_btn.set_margin_top(10)
        self.load_more_btn.set_margin_bottom(10)
        content_box.pack_start(self.load_more_btn, False, False, 0)

        paned.pack2(content_box, True, False)

        # --- Lejátszó Sáv (Lent) ---
        player_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        player_bar.get_style_context().add_class("player-bar")
        player_bar.set_size_request(-1, 80)
        main_box.pack_end(player_bar, False, False, 0)

        # Vezérlők
        self.btn_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.btn_play.connect("clicked", self.on_play_pause_clicked)
        self.btn_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        controls_box.pack_start(self.btn_prev, False, False, 0)
        controls_box.pack_start(self.btn_play, False, False, 0)
        controls_box.pack_start(self.btn_next, False, False, 0)
        player_bar.pack_start(controls_box, False, False, 0)

        # Meta infó
        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.lbl_title = ScrollingLabel()
        self.lbl_title.set_markup("<b>Nincs lejátszás</b>")
        self.lbl_artist = ScrollingLabel()
        meta_box.pack_start(self.lbl_title, True, True, 0)
        meta_box.pack_start(self.lbl_artist, True, True, 0)
        player_bar.pack_start(meta_box, True, True, 0)

        # Hangerő
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        vol_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic", Gtk.IconSize.MENU)
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
        self.volume_scale.set_value(0.5)
        self.volume_scale.set_size_request(100, -1)
        self.volume_scale.connect("value-changed", self.on_volume_changed)
        
        vol_box.pack_start(vol_icon, False, False, 0)
        vol_box.pack_start(self.volume_scale, False, False, 0)
        player_bar.pack_end(vol_box, False, False, 0)

        # Kedvenc gomb
        self.btn_fav = Gtk.Button.new_from_icon_name("non-starred-symbolic", Gtk.IconSize.BUTTON)
        self.btn_fav.connect("clicked", self.on_favorite_toggle)
        player_bar.pack_end(self.btn_fav, False, False, 0)

    def add_sidebar_item(self, id, title, icon_name):
        row = Gtk.ListBoxRow()
        row.id = id
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.get_style_context().add_class("sidebar-row")
        
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        label = Gtk.Label(label=title)
        
        box.pack_start(icon, False, False, 0)
        box.pack_start(label, False, False, 0)
        row.add(box)
        self.sidebar_list.add(row)

    def load_radios_bg(self):
        GLib.idle_add(self.status_label.set_text, "Adatok letöltése...")
        try:
            # Cache ellenőrzése (verziózott cache fájl a frissítés kényszerítéséhez)
            cache_file = "radios_cache_v2.json.bz2"
            if os.path.exists(cache_file):
                with bz2.open(cache_file, "rt") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.radios = data.get('radios', [])
                    else:
                        self.radios = data
            else:
                # API hívás - Növelt limit (50.000 helyett 100.000 a biztonság kedvéért)
                response = requests.get("https://de1.api.radio-browser.info/json/stations?limit=100000", timeout=15)
                if response.status_code == 200:
                    self.radios = response.json()
                    with bz2.open(cache_file, "wt") as f:
                        json.dump({'radios': self.radios}, f)
            
            GLib.idle_add(self.on_radios_loaded)
        except Exception as e:
            print(f"Hiba: {e}")
            GLib.idle_add(self.status_label.set_text, "Hiba a betöltéskor!")

    def populate_sidebar(self):
        # Törlés
        for child in self.sidebar_list.get_children():
            self.sidebar_list.remove(child)
            
        # Fix elemek
        self.add_sidebar_item("all", "Összes Rádió", "network-transmit-receive-symbolic")
        self.add_sidebar_item("favorites", "Kedvencek", "starred-symbolic")
        self.add_sidebar_item("tv", "ÉlőTv", "video-display-symbolic")
        
        # Országok gyűjtése
        countries = set()
        for radio in self.radios:
            c = radio.get('country')
            if c:
                countries.add(c)
        
        for country in sorted(countries):
            self.add_sidebar_item(f"country:{country}", country, "globe-symbolic")
            
        self.sidebar_list.show_all()

    def on_radios_loaded(self):
        # 1. Deduplikálás és szűrés (csak működő)
        unique_radios = {}
        for radio in self.radios:
            # Csak ha a lastcheckok 1 (működő), vagy nincs ilyen mező
            if 'lastcheckok' in radio and str(radio['lastcheckok']) == '0':
                continue
                
            uuid = radio.get('stationuuid')
            if uuid and uuid not in unique_radios:
                unique_radios[uuid] = radio
        
        self.radios = list(unique_radios.values())
        self.status_label.set_text(f"Összesen {len(self.radios)} rádió elérhető")
        
        # Sidebar frissítése az új adatokkal
        self.populate_sidebar()
        self.filter_radios()

    def on_category_selected(self, listbox, row):
        if row:
            self.filter_radios()

    def on_search_changed(self, entry):
        self.filter_radios()

    def filter_radios(self):
        query = self.search_entry.get_text().lower()
        selected_row = self.sidebar_list.get_selected_row()
        category = selected_row.id if selected_row else "all"

        filtered = []
        
        # Forrás lista meghatározása
        if category == "favorites":
            source_list = [r for r in self.radios if r['stationuuid'] in self.favorites]
        elif category == "tv":
            # TV csatornák szűrése címkék alapján
            source_list = [r for r in self.radios if 'tv' in r.get('tags', '').lower().split(',') or 'video' in r.get('tags', '').lower() or 'television' in r.get('tags', '').lower()]
        elif category.startswith("country:"):
            country_name = category.split(":", 1)[1]
            source_list = [r for r in self.radios if r.get('country') == country_name]
        else:
            source_list = self.radios

        # Keresés
        for radio in source_list:
            if query:
                if query in radio.get('name', '').lower() or query in radio.get('tags', '').lower():
                    filtered.append(radio)
            else:
                filtered.append(radio)

        self.filtered_radios = filtered
        self.displayed_count = 50 # Reset
        self.update_flowbox()

    def update_flowbox(self):
        # Törlés
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

        # Új elemek
        count = 0
        for radio in self.filtered_radios:
            if count >= self.displayed_count:
                break
            
            card = self.create_radio_card(radio)
            self.flowbox.add(card)
            count += 1
        
        self.flowbox.show_all()
        
        # Státusz frissítése
        visible = min(self.displayed_count, len(self.filtered_radios))
        total = len(self.filtered_radios)
        self.status_label.set_text(f"Megjelenítve: {visible} / {total}")
        self.load_more_btn.set_visible(visible < total)

    def create_radio_card(self, radio):
        # Kártya konténer (Button, hogy kattintható legyen)
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.get_style_context().add_class("radio-card")
        btn.set_size_request(140, 160) # Fix méret a kártyának
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        btn.add(box)

        # Ikon
        icon = Gtk.Image()
        icon.set_pixel_size(64)
        icon.set_halign(Gtk.Align.CENTER)
        
        favicon = radio.get('favicon')
        if favicon:
            self.executor.submit(self.load_image, icon, favicon, radio.get('stationuuid'))
        else:
            icon.set_from_icon_name("audio-x-generic", Gtk.IconSize.DIALOG)
            
        box.pack_start(icon, True, True, 0)

        # Cím
        lbl_name = Gtk.Label(label=radio.get('name', 'Névtelen'))
        lbl_name.set_ellipsize(Pango.EllipsizeMode.END)
        lbl_name.set_max_width_chars(15)
        lbl_name.set_halign(Gtk.Align.CENTER)
        lbl_name.get_style_context().add_class("card-title")
        box.pack_start(lbl_name, False, False, 0)

        # Ország / Info
        lbl_info = Gtk.Label(label=radio.get('country', ''))
        lbl_info.set_ellipsize(Pango.EllipsizeMode.END)
        lbl_info.set_max_width_chars(15)
        lbl_info.set_halign(Gtk.Align.CENTER)
        lbl_info.get_style_context().add_class("dim-label")
        box.pack_start(lbl_info, False, False, 0)

        # Klikk esemény
        btn.connect("clicked", lambda b: self.play_radio(radio))
        
        return btn

    def load_image(self, image_widget, url, uuid):
        if not url: return
        
        # Helyi cache mappa
        if not os.path.exists("logos"):
            os.makedirs("logos", exist_ok=True)
            
        # Kiterjesztés kitalálása
        ext = os.path.splitext(url)[1].lower()
        if len(ext) > 5 or not ext: ext = ".png"
        local_path = os.path.join("logos", f"{uuid}{ext}")

        try:
            # Letöltés
            if not os.path.exists(local_path):
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        # Ellenőrizzük, hogy nem HTML-e (pl. 404 oldal)
                        if 'text/html' in resp.headers.get('content-type', '').lower():
                            return
                        with open(local_path, "wb") as f:
                            f.write(resp.content)
                    else:
                        return
                except:
                    return

            if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
                return

            # SVG detektálása (kiterjesztés vagy tartalom alapján)
            is_svg = url.lower().endswith('.svg')
            if not is_svg:
                try:
                    with open(local_path, 'rb') as f:
                        header = f.read(100)
                        if b'<svg' in header or b'<!DOCTYPE svg' in header:
                            is_svg = True
                except: pass

            if is_svg:
                # SVG-t a GdkPixbuf kezeli natívan
                try:
                    loader = GdkPixbuf.PixbufLoader()
                    with open(local_path, 'rb') as f:
                        loader.write(f.read())
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        scaled = pixbuf.scale_simple(64, 64, GdkPixbuf.InterpType.BILINEAR)
                        GLib.idle_add(image_widget.set_from_pixbuf, scaled)
                except: pass
                return

            # Egyéb képek Pillow-val (robusztusabb)
            success = False
            try:
                with Image.open(local_path) as img:
                    # CMYK konvertálása RGB-be (PNG nem támogatja a CMYK-t)
                    if img.mode == 'CMYK':
                        img = img.convert('RGB')
                    
                    img.thumbnail((64, 64), Image.Resampling.LANCZOS)
                    
                    byte_arr = io.BytesIO()
                    img.save(byte_arr, format='PNG')
                    data = byte_arr.getvalue()
                    
                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    
                    if pixbuf:
                        GLib.idle_add(image_widget.set_from_pixbuf, pixbuf)
                        success = True
            except Exception as e:
                pass

            if not success:
                # Fallback: GdkPixbuf (hátha ő ismeri, pl. speciális ikonok)
                try:
                    loader = GdkPixbuf.PixbufLoader()
                    with open(local_path, 'rb') as f:
                        loader.write(f.read())
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        scaled = pixbuf.scale_simple(64, 64, GdkPixbuf.InterpType.BILINEAR)
                        GLib.idle_add(image_widget.set_from_pixbuf, scaled)
                        success = True
                except:
                    pass
            
            # Ha minden kötél szakad és a fájl hibás, töröljük
            if not success and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except:
                    pass

        except Exception as e:
            # print(f"Logo hiba: {e}")
            pass

    def on_load_more(self, btn):
        self.displayed_count += 50
        self.update_flowbox()

    def on_sync_message(self, bus, msg):
        # Videó ablak kezelése
        if msg.get_structure().get_name() == "prepare-window-handle":
            if self.video_xid:
                try:
                    # GStreamer kéri az ablakot - Egyszerű és működő módszer
                    msg.src.set_window_handle(self.video_xid)
                except Exception as e:
                    print(f"Video overlay hiba: {e}")
                
                def show_win():
                    self.video_window.set_title("ÉlőTv")
                    self.video_window.show_all()
                    return False
                
                # Megjelenítjük az ablakot (főszálon)
                GLib.idle_add(show_win)

    def on_video_window_close(self, widget, event):
        # Nem zárjuk be, csak elrejtjük
        self.player.set_state(Gst.State.NULL) # Leállítjuk a lejátszást is
        self.btn_play.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        widget.hide()
        return True

    def play_radio(self, radio):
        self.current_radio = radio
        
        # Videó ablak elrejtése (ha előzőleg nyitva volt)
        self.video_window.hide()
        
        # UI frissítés
        self.lbl_title.set_markup(f"<b>{radio.get('name')}</b>")
        self.lbl_artist.set_text(f"{radio.get('country')} - {radio.get('tags')}")
        self.btn_play.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        
        # Kedvenc ikon frissítése
        self.update_favorite_icon()

        # Lejátszás indítása háttérszálon (playlist feloldás miatt)
        threading.Thread(target=self.start_playback_async, args=(radio.get('url'),), daemon=True).start()

    def start_playback_async(self, url):
        resolved = self.resolve_url(url)
        print(f"Lejátszás indítása: {resolved}")
        GLib.idle_add(self.start_gstreamer, resolved)

    def start_gstreamer(self, url):
        self.player.set_state(Gst.State.NULL)
        self.player.set_property("uri", url)
        self.player.set_state(Gst.State.PLAYING)

    def resolve_url(self, url):
        # Playlist fájlok (.m3u, .pls) manuális feloldása, 
        # mert a GStreamer néha elhasal rajtuk (text/uri-list hiba)
        # DE: Modern streaming formátumokat (HLS, DASH, Video) NE bántsuk!
        skip_extensions = ('.m3u8', '.mpd', '.mp4', '.webm', '.mkv', '.flv')
        if url.lower().endswith(('.m3u', '.pls')) and not url.lower().endswith(skip_extensions):
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    content = resp.text
                    lines = content.splitlines()
                    
                    # PLS formátum
                    if 'pls' in url.lower() or '[playlist]' in content.lower():
                        for line in lines:
                            if line.lower().strip().startswith('file1='):
                                return line.split('=', 1)[1].strip()
                    
                    # M3U formátum (első érvényes URL)
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#') and line.startswith('http'):
                            return line
            except Exception as e:
                print(f"Playlist feloldási hiba: {e}")
        return url

    def on_play_pause_clicked(self, btn):
        _, state, _ = self.player.get_state(Gst.CLOCK_TIME_NONE)
        if state == Gst.State.PLAYING:
            self.player.set_state(Gst.State.PAUSED)
            self.btn_play.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        else:
            self.player.set_state(Gst.State.PLAYING)
            self.btn_play.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.LARGE_TOOLBAR))

    def on_volume_changed(self, scale):
        self.player.set_property("volume", scale.get_value())

    def on_favorite_toggle(self, btn):
        if not self.current_radio: return
        
        uuid = self.current_radio['stationuuid']
        if uuid in self.favorites:
            self.favorites.remove(uuid)
        else:
            self.favorites.add(uuid)
        
        self.save_favorites()
        self.update_favorite_icon()
        
        # Ha a kedvencek nézetben vagyunk, frissíteni kell a listát
        selected = self.sidebar_list.get_selected_row()
        if selected and selected.id == "favorites":
            self.filter_radios()

    def update_favorite_icon(self):
        if not self.current_radio: return
        uuid = self.current_radio['stationuuid']
        icon = "starred-symbolic" if uuid in self.favorites else "non-starred-symbolic"
        self.btn_fav.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))

    def get_config_dir(self):
        config_dir = os.path.join(GLib.get_user_config_dir(), "gladeradio")
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        return config_dir

    def load_favorites(self):
        config_file = os.path.join(self.get_config_dir(), "favorites.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    self.favorites = set(json.load(f))
            except:
                self.favorites = set()

    def save_favorites(self):
        config_file = os.path.join(self.get_config_dir(), "favorites.json")
        with open(config_file, "w") as f:
            json.dump(list(self.favorites), f)

    def on_source_setup(self, element, source):
        try:
            if source.has_property("user-agent"):
                source.set_property("user-agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            if source.has_property("ssl-strict"):
                source.set_property("ssl-strict", False)
        except:
            pass

    def on_tag_message(self, bus, msg):
        # Metaadatok (pl. éppen játszott dal) frissítése
        taglist = msg.parse_tag()
        # Itt lehetne bővíteni a UI-t dinamikus infókkal
        pass

    def on_player_error(self, bus, msg):
        err, debug = msg.parse_error()
        print(f"Lejátszási hiba: {err}, {debug}")
        
        msg_text = err.message
        debug_str = str(debug) if debug else ""
        
        # Felhasználóbarát hibaüzenetek
        if "Not Found" in msg_text or "404" in debug_str:
            msg_text = "Az adás nem elérhető (404 - Offline)"
        elif "Forbidden" in msg_text or "403" in debug_str:
            msg_text = "Hozzáférés megtagadva (403)"
        elif "Connection refused" in msg_text or "connection refused" in debug_str:
            msg_text = "A szerver nem válaszol"
        elif "GstTypeFindElement" in debug_str or "missing plugin" in debug_str.lower():
            msg_text = "Hiányzó kodek! (gstreamer-plugins-ugly/bad)"
        elif "Internal data stream error" in msg_text:
            msg_text = "Adatfolyam hiba (Lehet, hogy offline)"
            
        # UI frissítése
        self.lbl_artist.set_text(f"Hiba: {msg_text}")
        self.btn_play.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.LARGE_TOOLBAR))

if __name__ == "__main__":
    win = RadioApp()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
