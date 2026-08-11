"""
Interactive picking for the stereonet plot.

StereonetPickHandler connects to the live FigureCanvasQTAgg, resolves
matplotlib pick events back to QGIS features via the per-render registry
({artist: [(dataset_idx, feature_id), ...]} built in core._render_stereonet_into),
applies the selection to the source layers, and draws highlight rings on the
picked points.

Interaction model:
- Left-click a point: select that feature (replaces selection on all plotted
  layers). Coincident/overlapping points within the pick radius all select.
- Ctrl + left-click: add to the current selection.
- Shift + left-drag: rubber-band rectangle select (replaces); Ctrl+Shift+drag
  adds to the current selection.
- Left-click on an empty part of the stereonet axes: clear selection on the
  plotted layers. Clicks outside the axes (legend, margins) are ignored.
- Right-press and hold: probe - shows the great circle of the plane whose
  pole sits under the cursor plus a two-line dip/dip-direction and
  plunge/trend readout in the bottom-left corner of the canvas; dragging
  moves it, releasing hides it.
- Right double-click: pin the probed plane/line into the plot (stored as
  data on the controller, so pins survive replots and appear in exports).
  Right double-click on a pinned pole removes that pin.
"""

import numpy as np
from matplotlib.patches import Rectangle

from ..vendor.mplstereonet import stereonet_math

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsMessageLog, QgsVectorLayer, Qgis

FALLBACK_HIGHLIGHT_COLOR = '#FFD700'  # QGIS's default yellow selection colour

PIN_HIT_RADIUS_PX = 10.0  # right double-click within this of a pinned pole unpins it


class StereonetPickHandler:
    """Routes matplotlib pick events on the stereonet canvas to QGIS feature
    selection. One instance per stereonet controller; survives re-renders
    (set_plot() is called with a fresh registry after each render)."""

    def __init__(self, controller):
        self.controller = controller
        self.canvas = None
        self._cids = []
        self._registry = {}
        self._plot_datasets = set()
        self._highlight_artists = []
        # Per-click accumulation: matplotlib fires one pick_event per hit
        # artist plus a button_press_event, all sharing one MouseEvent.
        # Handlers accumulate here and a zero-delay QTimer processes the
        # click once the Qt event loop runs (i.e. after all mpl callbacks).
        # _pending_additive doubles as the "click scheduled" marker (None =
        # nothing pending), so a set_plot() reset orphans any queued callback.
        self._pending_hits = []
        self._pending_additive = None
        # Shift+drag rectangle-select state (pixel coords; rubber band drawn
        # by blitting over a cached background)
        self._drag_origin = None
        self._drag_additive = False
        self._drag_rect = None
        self._drag_background = None
        # Right-press-and-hold plane probe state. Artists are created lazily
        # per render (figure.clear() on re-render destroys them) and marked
        # animated so normal renders/exports never include them.
        self._probe_ax = None
        self._probe_active = False
        self._probe_background = None
        self._probe_line = None
        self._probe_marker = None
        self._probe_text = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self, canvas):
        self.canvas = canvas
        self._cids = [
            canvas.mpl_connect('pick_event', self.on_pick),
            canvas.mpl_connect('button_press_event', self.on_button_press),
            canvas.mpl_connect('motion_notify_event', self.on_motion),
            canvas.mpl_connect('button_release_event', self.on_release),
            canvas.mpl_connect('resize_event', self._on_canvas_resize),
        ]

    def disconnect(self):
        if self.canvas is not None:
            for cid in self._cids:
                try:
                    self.canvas.mpl_disconnect(cid)
                except Exception:
                    pass
        self._cids = []
        self.canvas = None
        # Neutralise any click callback still queued on the event loop
        # (_process_click bails out when canvas is None / nothing pending)
        self.set_plot({})

    def set_plot(self, registry, ax=None):
        """Called after every render (or clear). The previous figure contents
        are gone, so just forget old highlight artists rather than remove().
        ax is the freshly rendered stereonet axes (None disables the probe)."""
        self._registry = dict(registry) if registry else {}
        self._plot_datasets = {
            dataset_idx
            for entries in self._registry.values()
            for dataset_idx, _fid in entries
        }
        self._highlight_artists = []
        self._pending_hits = []
        self._pending_additive = None
        self._reset_drag()
        self._reset_probe(ax)

    def _reset_drag(self):
        """Forget drag state without touching the (possibly dead) figure."""
        if self._drag_rect is not None:
            try:
                self._drag_rect.remove()
            except Exception:
                pass
        self._drag_rect = None
        self._drag_background = None
        self._drag_origin = None

    def _reset_probe(self, ax):
        """Forget probe state after a render/clear. Artist references are
        dropped without remove() - the figure they lived on was cleared."""
        self._probe_ax = ax
        self._probe_active = False
        self._probe_background = None
        self._probe_line = None
        self._probe_marker = None
        self._probe_text = None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_pick(self, event):
        mouseevent = getattr(event, 'mouseevent', None)
        if mouseevent is None or mouseevent.button != 1:
            return
        # Shift starts a rectangle drag - discard the picks its initial
        # press generates (live modifier check, so this holds regardless of
        # matplotlib's pick-vs-press callback ordering)
        if self._drag_origin is not None or self._is_shift(mouseevent):
            return
        if event.artist not in self._registry:
            return
        self._pending_hits.append((event.artist, event.ind))
        self._schedule(mouseevent)

    def on_button_press(self, event):
        if event.button == 3:
            # A double-click arrives as press/release/press(dblclick)/release;
            # the first press already started a probe, so hide it before
            # pinning (the trailing release then no-ops on _probe_active)
            if getattr(event, 'dblclick', False):
                if self._probe_active:
                    self._end_probe()
                self._toggle_pin(event)
                return
            self._start_probe(event)
            return
        if event.button != 1:
            return
        # Only clicks inside the plot axes count as "empty area" (so clicking
        # the legend, stat text or figure margin never clears the selection).
        # Point hits are scheduled by on_pick regardless.
        if event.inaxes is None:
            return
        if self._is_shift(event):
            self._start_drag(event)
            return
        self._schedule(event)

    def on_motion(self, event):
        if self._probe_active:
            self._update_probe(event)
            return
        if self._drag_origin is None or self.canvas is None:
            return
        if event.x is None or event.y is None:
            return
        x0, y0 = self._drag_origin
        if self._drag_rect is None:
            # transform=None -> IdentityTransform: corners are pixel coords
            self._drag_rect = Rectangle((0, 0), 0, 0, fill=False,
                                        linestyle='--', linewidth=1.2,
                                        edgecolor='#606060', transform=None,
                                        animated=True, zorder=20)
            self.canvas.figure.add_artist(self._drag_rect)
        self._drag_rect.set_bounds(min(x0, event.x), min(y0, event.y),
                                   abs(event.x - x0), abs(event.y - y0))
        if self._drag_background is not None:
            self.canvas.restore_region(self._drag_background)
            self.canvas.figure.draw_artist(self._drag_rect)
            self.canvas.blit(self.canvas.figure.bbox)
        else:
            self.canvas.draw_idle()

    def on_release(self, event):
        if event.button == 3:
            if self._probe_active:
                self._end_probe()
            return
        if self._drag_origin is None or event.button != 1:
            return
        x0, y0 = self._drag_origin
        additive = self._drag_additive
        self._end_drag_visual()
        self._drag_origin = None

        if self.canvas is None:
            return
        x1 = event.x if event.x is not None else x0
        y1 = event.y if event.y is not None else y0
        xmin, xmax = sorted((x0, x1))
        ymin, ymax = sorted((y0, y1))
        if (xmax - xmin) < 3 and (ymax - ymin) < 3:
            # Shift+click without a real drag: behave like a pick-radius click
            xmin -= 6
            xmax += 6
            ymin -= 6
            ymax += 6

        hits = []
        for artist in self._registry:
            ax = artist.axes
            if ax is None:
                continue
            xd = np.asarray(artist.get_xdata(), dtype=float)
            yd = np.asarray(artist.get_ydata(), dtype=float)
            if xd.size == 0:
                continue
            pts = ax.transData.transform(np.column_stack([xd, yd]))
            mask = ((pts[:, 0] >= xmin) & (pts[:, 0] <= xmax) &
                    (pts[:, 1] >= ymin) & (pts[:, 1] <= ymax))
            ind = np.nonzero(mask)[0]
            if ind.size:
                hits.append((artist, ind))

        if hits:
            self._select_hits(hits, additive)
        elif not additive:
            # Empty rectangle replaces the selection with nothing, matching
            # QGIS's map-canvas rectangle select
            self._clear_all()

    def _start_drag(self, event):
        self._drag_origin = (event.x, event.y)
        self._drag_additive = self._is_additive(event)
        self._drag_rect = None
        try:
            self._drag_background = self.canvas.copy_from_bbox(
                self.canvas.figure.bbox)
        except Exception:
            self._drag_background = None  # on_motion falls back to draw_idle

    def _end_drag_visual(self):
        if self._drag_rect is not None:
            try:
                self._drag_rect.remove()
            except Exception:
                pass
            self._drag_rect = None
        if self.canvas is not None:
            if self._drag_background is not None:
                try:
                    self.canvas.restore_region(self._drag_background)
                    self.canvas.blit(self.canvas.figure.bbox)
                except Exception:
                    self.canvas.draw_idle()
            else:
                self.canvas.draw_idle()
        self._drag_background = None

    # ------------------------------------------------------------------
    # Plane probe (right-press and hold)
    # ------------------------------------------------------------------

    def _on_canvas_resize(self, _event):
        # A resize invalidates the cached blit background pixel-for-pixel
        if self._probe_active:
            self._end_probe()
        self._probe_background = None

    def _event_lonlat(self, event):
        """Pixel coords -> (lon, lat) radians on the stereonet axes, or None
        if there is no rendered plot or the cursor is outside the net.

        Deliberately ignores event.xdata/ydata: the hidden polar overlay axes
        sits on top of the stereonet axes and usually owns event.inaxes, and
        its data coords are (theta, r), not (lon, lat)."""
        ax = self._probe_ax
        if ax is None or event.x is None or event.y is None:
            return None
        try:
            if not ax.patch.contains_point((event.x, event.y)):
                return None
            lon, lat = ax.transData.inverted().transform((event.x, event.y))
        except Exception:
            return None
        if not (np.isfinite(lon) and np.isfinite(lat)):
            return None
        return float(lon), float(lat)

    def _ensure_probe_artists(self):
        if self._probe_line is not None:
            return
        ax = self._probe_ax
        self._probe_line, = ax.plot([], [], color='#C0392B', lw=1.6,
                                    ls='--', animated=True, zorder=15)
        self._probe_marker, = ax.plot([], [], marker='o', ms=7, ls='none',
                                      mfc='#C0392B', mec='white', mew=1.0,
                                      animated=True, zorder=16)
        # Figure-anchored (bottom-left corner) so it can never clip at any
        # canvas size, but axes-owned so ax.draw_artist keeps blitting it
        self._probe_text = ax.text(0.012, 0.015, '',
                                   transform=ax.figure.transFigure,
                                   ha='left', va='bottom', fontsize=9,
                                   linespacing=1.3, animated=True, zorder=16,
                                   bbox=dict(boxstyle='round,pad=0.3',
                                             fc='white', ec='#999999',
                                             alpha=0.9))

    def _start_probe(self, event):
        if self.canvas is None or self._event_lonlat(event) is None:
            return
        self._ensure_probe_artists()
        try:
            # Flush any pending draw_idle so the copied background is current
            self.canvas.draw()
            self._probe_background = self.canvas.copy_from_bbox(
                self.canvas.figure.bbox)
        except Exception:
            self._probe_background = None  # motion falls back to draw_idle
        self._probe_active = True
        self._update_probe(event)

    def _update_probe(self, event):
        res = self._event_lonlat(event)
        if res is None:
            # Dragged off the net / off the canvas: hide until it re-enters
            self._blit_probe(visible=False)
            return
        lon, lat = res
        plunge, bearing = stereonet_math.geographic2plunge_bearing(lon, lat)
        strike, dip = stereonet_math.geographic2pole(lon, lat)
        plunge, bearing = float(plunge[0]), float(bearing[0])
        strike, dip = float(strike[0]), float(dip[0])
        dip_dir = (strike + 90.0) % 360.0

        lon_gc, lat_gc = stereonet_math.plane(strike, dip)
        self._probe_line.set_data(lon_gc.ravel(), lat_gc.ravel())
        self._probe_marker.set_data([lon], [lat])
        self._probe_text.set_text(
            u"Plane {:02.0f}°/{:03.0f}° (dip/dip dir)\n"
            u"Line {:02.0f}°→{:03.0f}° (plunge/trend)".format(
                dip, dip_dir, plunge, bearing))
        self._blit_probe(visible=True)

    def _blit_probe(self, visible):
        for art in (self._probe_line, self._probe_marker, self._probe_text):
            if art is not None:
                art.set_visible(visible)
        if self.canvas is None:
            return
        if self._probe_background is not None:
            try:
                self.canvas.restore_region(self._probe_background)
                if visible:
                    ax = self._probe_ax
                    ax.draw_artist(self._probe_line)
                    ax.draw_artist(self._probe_marker)
                    ax.draw_artist(self._probe_text)
                self.canvas.blit(self.canvas.figure.bbox)
                return
            except Exception:
                pass
        self.canvas.draw_idle()

    def _end_probe(self):
        self._probe_active = False
        self._blit_probe(visible=False)
        self._probe_background = None

    # ------------------------------------------------------------------
    # Pinned probes (right double-click)
    # ------------------------------------------------------------------

    def _toggle_pin(self, event):
        res = self._event_lonlat(event)
        if res is None:
            return
        hit = self._find_pin_near(event)
        if hit is not None:
            self.controller.remove_stereonet_pin(hit)
            self._show_status("Stereonet: pin removed")
            return
        lon, lat = res
        plunge, bearing = stereonet_math.geographic2plunge_bearing(lon, lat)
        strike, dip = stereonet_math.geographic2pole(lon, lat)
        strike, dip = float(strike[0]), float(dip[0])
        dip_dir = (strike + 90.0) % 360.0
        self.controller.add_stereonet_pin({
            'dip': dip, 'dip_dir': dip_dir, 'strike': strike,
            'plunge': float(plunge[0]), 'bearing': float(bearing[0]),
            'lon': lon, 'lat': lat,
        })
        self._show_status(
            "Stereonet: pinned plane {:02.0f}/{:03.0f} "
            "(right double-click it to remove)".format(dip, dip_dir))

    def _find_pin_near(self, event):
        """Index of the pin whose pole is within PIN_HIT_RADIUS_PX of the
        cursor (nearest wins), else None. Hit-tests the stored pole position
        regardless of display mode so 'Plane only' pins stay removable."""
        ax = self._probe_ax
        pins = getattr(self.controller, 'stereonet_pins', None)
        if ax is None or not pins:
            return None
        try:
            pts = ax.transData.transform([(p['lon'], p['lat']) for p in pins])
        except Exception:
            return None
        d = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
        i = int(np.argmin(d))
        return i if d[i] <= PIN_HIT_RADIUS_PX else None

    def _schedule(self, mouseevent):
        additive = self._is_additive(mouseevent)
        if self._pending_additive is None:
            QTimer.singleShot(0, self._process_click)
        self._pending_additive = additive

    @staticmethod
    def _is_additive(mouseevent):
        # Qt's live modifier state is reliable across matplotlib versions;
        # mpl's MouseEvent.key needs canvas keyboard focus on older releases
        try:
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                return True
        except Exception:
            pass
        key = ''
        if mouseevent is not None and mouseevent.key:
            key = str(mouseevent.key).lower()
        return key in ('control', 'ctrl') or 'ctrl' in key.split('+')

    @staticmethod
    def _is_shift(mouseevent):
        try:
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
                return True
        except Exception:
            pass
        key = ''
        if mouseevent is not None and mouseevent.key:
            key = str(mouseevent.key).lower()
        return key == 'shift' or 'shift' in key.split('+')

    # ------------------------------------------------------------------
    # Click processing
    # ------------------------------------------------------------------

    def _process_click(self):
        hits = self._pending_hits
        additive = self._pending_additive
        self._pending_hits = []
        self._pending_additive = None

        # additive is None when set_plot()/disconnect() reset the pending
        # state after this callback was queued - the click belongs to a
        # plot that no longer exists, so ignore it
        if additive is None or self.canvas is None:
            return

        if not hits:
            # Plain click on empty axes area clears; Ctrl+click is a no-op
            if not additive:
                self._clear_all()
            return

        self._select_hits(hits, additive)

    def _select_hits(self, hits, additive):
        """Resolve (artist, indices) hits to features, apply the selection
        and draw highlights. Shared by click picking and rectangle select."""
        picks_by_dataset = {}
        missing_fid = 0
        for artist, ind in hits:
            entries = self._registry.get(artist)
            if not entries:
                continue
            for i in np.atleast_1d(ind):
                i = int(i)
                if i < 0 or i >= len(entries):
                    continue
                dataset_idx, fid = entries[i]
                if fid is None:
                    missing_fid += 1
                    continue
                picks_by_dataset.setdefault(dataset_idx, set()).add(fid)

        if missing_fid:
            QgsMessageLog.logMessage(
                f"Stereonet pick: {missing_fid} plotted point(s) have no source feature id",
                'Linear Geoscience', Qgis.MessageLevel.Warning)

        if not picks_by_dataset:
            # Points were hit but none could be linked to a feature: leave
            # the existing selection untouched and draw no highlight
            self._show_status("Stereonet: clicked point(s) have no linked features")
            return

        n_selected = self._apply_selection(picks_by_dataset, additive)
        if n_selected:
            self._draw_highlight(hits, additive)
            self._show_status(f"Stereonet: selected {n_selected} feature(s)")
        else:
            self._show_status("Stereonet: source layer(s) not available")

    def _show_status(self, message):
        try:
            self.controller.iface.mainWindow().statusBar().showMessage(message, 3000)
        except Exception:
            pass

    def _apply_selection(self, picks_by_dataset, additive):
        """Apply the picked feature ids to their layers; returns the number
        of features actually selected."""
        controller = self.controller

        # Group per layer (both datasets may point at the same QGIS layer)
        layers_with_picks = {}  # layer id -> (layer, set of fids)
        for dataset_idx, fids in picks_by_dataset.items():
            layer = controller.get_layer(dataset_idx)
            if layer is None:
                QgsMessageLog.logMessage(
                    f"Stereonet pick: layer for dataset {dataset_idx + 1} "
                    "not available, skipping selection",
                    'Linear Geoscience', Qgis.MessageLevel.Warning)
                continue
            _, merged = layers_with_picks.setdefault(layer.id(), (layer, set()))
            merged.update(fids)
        if not layers_with_picks:
            return 0

        controller._suppress_selection_replot = True
        try:
            for layer, fids in layers_with_picks.values():
                if additive:
                    layer.selectByIds(list(fids), Qgis.SelectBehavior.AddToSelection)
                else:
                    layer.selectByIds(list(fids))
            if not additive:
                # Replace semantics span the whole plot: clear plotted
                # layers that received no picks this click
                for dataset_idx in self._plot_datasets - set(picks_by_dataset):
                    layer = controller.get_layer(dataset_idx)
                    if layer is not None and layer.id() not in layers_with_picks:
                        layer.removeSelection()
        finally:
            controller._suppress_selection_replot = False
        return sum(len(fids) for _, fids in layers_with_picks.values())

    def _clear_all(self):
        controller = self.controller
        cleared_layer_ids = set()
        controller._suppress_selection_replot = True
        try:
            for dataset_idx in self._plot_datasets:
                layer = controller.get_layer(dataset_idx)
                if layer is not None and layer.id() not in cleared_layer_ids:
                    cleared_layer_ids.add(layer.id())
                    layer.removeSelection()
        finally:
            controller._suppress_selection_replot = False
        if self._remove_highlights() and self.canvas is not None:
            self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Highlight rings
    # ------------------------------------------------------------------

    def _highlight_color(self):
        """Match the rings to QGIS's (user-configurable) selection colour."""
        try:
            return self.controller.iface.mapCanvas().selectionColor().name()
        except Exception:
            return FALLBACK_HIGHLIGHT_COLOR

    def _draw_highlight(self, hits, additive):
        if not additive:
            self._remove_highlights()
        color = self._highlight_color()
        for artist, ind in hits:
            if artist not in self._registry:
                continue
            ax = artist.axes
            if ax is None:
                continue
            idx = np.atleast_1d(ind).astype(int)
            # The picked artist already holds projected stereonet coords, so
            # the rings need no pole/line transform of their own
            xs = np.asarray(artist.get_xdata())[idx]
            ys = np.asarray(artist.get_ydata())[idx]
            rings = ax.plot(xs, ys, marker='o', linestyle='none',
                            markerfacecolor='none',
                            markeredgecolor=color,
                            markeredgewidth=2.0, markersize=11, zorder=10)
            self._highlight_artists.extend(rings)
        if self.canvas is not None:
            self.canvas.draw_idle()

    def _remove_highlights(self):
        """Remove ring artists; returns True if any were removed."""
        removed = bool(self._highlight_artists)
        for art in self._highlight_artists:
            try:
                art.remove()
            except Exception:
                pass
        self._highlight_artists = []
        return removed
