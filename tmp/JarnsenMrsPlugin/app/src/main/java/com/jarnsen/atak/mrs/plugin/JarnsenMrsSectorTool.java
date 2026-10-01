package com.jarnsen.atak.mrs.plugin;

import android.graphics.Color;
import android.os.Bundle;
import android.widget.Toast;

import com.atakmap.android.maps.MapEvent;
import com.atakmap.android.maps.MapEventDispatcher;
import com.atakmap.android.maps.MapGroup;
import com.atakmap.android.maps.MapItem;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.maps.Marker;
import com.atakmap.android.maps.PointMapItem;
import com.atakmap.android.maps.Polyline;
import com.atakmap.android.maps.Shape;
import com.atakmap.android.toolbar.Tool;
import com.atakmap.android.toolbar.ToolManagerBroadcastReceiver;
import com.atakmap.android.toolbar.widgets.TextContainer;
import com.atakmap.android.util.ATAKUtilities;
import com.atakmap.coremap.maps.coords.GeoCalculations;
import com.atakmap.coremap.maps.coords.GeoPoint;
import com.atakmap.coremap.maps.coords.GeoPointMetaData;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * Draws the Jarnsen Mrs range sector from the ATAK self marker to a selected
 * map point.
 *
 * Map geometry is generated from the true geodetic bearing. The displayed
 * direction is converted to Grid North and NATO 6400 mil.
 */
public class JarnsenMrsSectorTool extends Tool
        implements MapEventDispatcher.MapEventDispatchListener,
        PointMapItem.OnPointChangedListener {

    public static final String TOOL_IDENTIFIER =
            "com.jarnsen.atak.mrs.tool.SECTOR";

    private static final double MAX_RANGE_M = 8000.0;
    private static final double RANGE_STEP_M = 500.0;

    // 600 NATO mil = 33.75 degrees.
    private static final double HALF_SECTOR_MIL = 600.0;
    private static final double HALF_SECTOR_DEG =
            HALF_SECTOR_MIL * 360.0 / 6400.0;

    private static final int COLOR_PRIMARY = Color.rgb(102, 245, 255);
    private static final int COLOR_PRIMARY_SOFT =
            Color.argb(180, 102, 245, 255);
    private static final int COLOR_PRIMARY_FAINT =
            Color.argb(130, 102, 245, 255);
    private static final int COLOR_FILL =
            Color.argb(42, 33, 182, 199);
    private static final int COLOR_TARGET =
            Color.rgb(255, 68, 68);

    private final MapView mapView;
    private final MapGroup overlayGroup;
    private final TextContainer prompt;

    private boolean selectionActive;

    private Marker selfMarker;
    private PointMapItem targetItem;
    private GeoPointMetaData targetPoint;

    public JarnsenMrsSectorTool(MapView mapView, MapGroup overlayGroup) {
        super(mapView, TOOL_IDENTIFIER);
        this.mapView = mapView;
        this.overlayGroup = overlayGroup;
        this.prompt = TextContainer.getInstance();

        ToolManagerBroadcastReceiver.getInstance().registerTool(
                TOOL_IDENTIFIER,
                this
        );

        attachSelfListener();
    }

    @Override
    public boolean onToolBegin(Bundle extras) {
        attachSelfListener();

        if (selfMarker == null || !isUsable(selfMarker.getPoint())) {
            Toast.makeText(
                    mapView.getContext(),
                    "Eigene Position ist noch nicht verfügbar.",
                    Toast.LENGTH_SHORT
            ).show();
            return false;
        }

        MapEventDispatcher dispatcher = mapView.getMapEventDispatcher();
        dispatcher.pushListeners();
        dispatcher.clearListeners(MapEvent.ITEM_CLICK);
        dispatcher.clearListeners(MapEvent.MAP_CLICK);
        dispatcher.addMapEventListener(MapEvent.ITEM_CLICK, this);
        dispatcher.addMapEventListener(MapEvent.MAP_CLICK, this);

        mapView.getMapTouchController().skipDeconfliction(true);
        prompt.displayPrompt("Jarnsen Mrs: Zielpunkt auf der Karte wählen");

        selectionActive = true;
        return true;
    }

    @Override
    public void onToolEnd() {
        if (selectionActive) {
            prompt.closePrompt();
            mapView.getMapEventDispatcher().popListeners();
            mapView.getMapTouchController().skipDeconfliction(false);
            selectionActive = false;
        }

        super.onToolEnd();
    }

    @Override
    public void onMapEvent(MapEvent event) {
        GeoPointMetaData clicked = findPoint(event);
        if (clicked == null || !isUsable(clicked.get())) {
            return;
        }

        if (selfMarker != null
                && selfMarker.getPoint().distanceTo(clicked.get()) < 1.0) {
            Toast.makeText(
                    mapView.getContext(),
                    "Bitte einen Zielpunkt ungleich der eigenen Position wählen.",
                    Toast.LENGTH_SHORT
            ).show();
            return;
        }

        setTarget(clicked, event.getItem());
        requestEndTool();
    }

    @Override
    public void onPointChanged(PointMapItem item) {
        if (item == null) {
            return;
        }

        if (item == targetItem) {
            targetPoint = item.getGeoPointMetaData();
        }

        redraw();
    }

    @Override
    public void dispose() {
        if (selectionActive) {
            requestEndTool();
        }

        detachTargetListener();

        if (selfMarker != null) {
            selfMarker.removeOnPointChangedListener(this);
            selfMarker = null;
        }

        overlayGroup.clearItems();

        ToolManagerBroadcastReceiver.getInstance().unregisterTool(
                TOOL_IDENTIFIER
        );
    }

    private void attachSelfListener() {
        Marker current = mapView.getSelfMarker();
        if (current == selfMarker) {
            return;
        }

        if (selfMarker != null) {
            selfMarker.removeOnPointChangedListener(this);
        }

        selfMarker = current;
        if (selfMarker != null) {
            selfMarker.addOnPointChangedListener(this);
        }
    }

    private void setTarget(GeoPointMetaData point, MapItem item) {
        detachTargetListener();

        targetPoint = point;

        if (item instanceof PointMapItem && item != selfMarker) {
            targetItem = (PointMapItem) item;
            targetItem.addOnPointChangedListener(this);
            targetPoint = targetItem.getGeoPointMetaData();
        }

        redraw();
    }

    private void detachTargetListener() {
        if (targetItem != null) {
            targetItem.removeOnPointChangedListener(this);
            targetItem = null;
        }
    }

    private void redraw() {
        overlayGroup.clearItems();
        attachSelfListener();

        if (selfMarker == null || targetPoint == null) {
            return;
        }

        GeoPoint own = selfMarker.getPoint();
        GeoPoint target = targetPoint.get();

        if (!isUsable(own) || !isUsable(target)) {
            return;
        }

        double targetDistance = own.distanceTo(target);
        if (Double.isNaN(targetDistance) || targetDistance < 1.0) {
            return;
        }

        double trueBearing = normalizeDegrees(own.bearingTo(target));
        double gridBearing = toGridBearing(own, target, trueBearing);
        int gridMil = degreesToMil(gridBearing);

        addSectorFill(own, trueBearing);
        addSectorBoundary(own, trueBearing - HALF_SECTOR_DEG);
        addSectorBoundary(own, trueBearing + HALF_SECTOR_DEG);

        for (double range = RANGE_STEP_M;
             range <= MAX_RANGE_M + 0.1;
             range += RANGE_STEP_M) {
            boolean fullKm = (((int) Math.round(range)) % 1000) == 0;
            addRangeArc(own, trueBearing, range, fullKm);
            addRangeTick(own, trueBearing, range, fullKm);
            addRangeLabel(own, trueBearing, range);
        }

        addCenterLine(own, target);
        addArrowHead(target, trueBearing);
        addTargetLabel(target, trueBearing);

        addCenterBracket(own, trueBearing);
        addBracketLabel(
                own,
                trueBearing,
                4000.0,
                185.0,
                String.format(Locale.GERMANY, "%04d Str GN", gridMil)
        );
        addBracketLabel(
                own,
                trueBearing,
                4000.0,
                -185.0,
                formatTargetDistance(targetDistance)
        );
    }

    private void addSectorFill(GeoPoint own, double bearing) {
        List<GeoPoint> pts = new ArrayList<>();
        pts.add(own);

        final int steps = 56;
        double start = bearing - HALF_SECTOR_DEG;
        double span = HALF_SECTOR_DEG * 2.0;

        for (int i = 0; i <= steps; i++) {
            double b = start + span * i / steps;
            pts.add(GeoCalculations.pointAtDistance(own, b, MAX_RANGE_M));
        }

        pts.add(own);

        Polyline sector = makePolyline(
                pts,
                COLOR_PRIMARY_FAINT,
                1.0,
                Shape.BASIC_LINE_STYLE_SOLID
        );
        sector.setStyle(
                Polyline.STYLE_CLOSED_MASK
                        | Shape.STYLE_STROKE_MASK
                        | Shape.STYLE_FILLED_MASK
        );
        sector.setFillColor(COLOR_FILL);
        addLocalItem(sector);
    }

    private void addSectorBoundary(GeoPoint own, double bearing) {
        List<GeoPoint> pts = new ArrayList<>();
        pts.add(own);
        pts.add(GeoCalculations.pointAtDistance(own, bearing, MAX_RANGE_M));

        addLocalItem(makePolyline(
                pts,
                Color.WHITE,
                2.3,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
    }

    private void addRangeArc(
            GeoPoint own,
            double bearing,
            double range,
            boolean fullKm) {

        List<GeoPoint> pts = new ArrayList<>();

        final int steps = 42;
        double start = bearing - HALF_SECTOR_DEG;
        double span = HALF_SECTOR_DEG * 2.0;

        for (int i = 0; i <= steps; i++) {
            double b = start + span * i / steps;
            pts.add(GeoCalculations.pointAtDistance(own, b, range));
        }

        Polyline arc = makePolyline(
                pts,
                fullKm ? COLOR_PRIMARY : COLOR_PRIMARY_SOFT,
                fullKm ? 2.3 : 1.15,
                fullKm
                        ? Shape.BASIC_LINE_STYLE_SOLID
                        : Shape.BASIC_LINE_STYLE_DASHED
        );

        addLocalItem(arc);
    }

    private void addRangeTick(
            GeoPoint own,
            double bearing,
            double range,
            boolean fullKm) {

        double halfWidth = fullKm ? 55.0 : 38.0;

        List<GeoPoint> pts = new ArrayList<>();
        pts.add(pointFromAxis(own, bearing, range, halfWidth));
        pts.add(pointFromAxis(own, bearing, range, -halfWidth));

        addLocalItem(makePolyline(
                pts,
                Color.WHITE,
                fullKm ? 2.0 : 1.2,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
    }

    /**
     * The distance text is carried by a short line segment immediately before
     * the corresponding arc, so the label stays aligned with the centerline
     * and appears on the own-position side of the range crossing.
     */
    private void addRangeLabel(
            GeoPoint own,
            double bearing,
            double range) {

        double start = Math.max(40.0, range - 245.0);
        double end = Math.max(80.0, range - 45.0);

        List<GeoPoint> pts = new ArrayList<>();
        pts.add(GeoCalculations.pointAtDistance(own, bearing, start));
        pts.add(GeoCalculations.pointAtDistance(own, bearing, end));

        Polyline labelLine = makePolyline(
                pts,
                Color.argb(1, 255, 255, 255),
                0.1,
                Shape.BASIC_LINE_STYLE_SOLID
        );

        labelLine.toggleMetaData("labels_on", true);
        labelLine.setLineLabel(formatRange(range));
        labelLine.setLabelTextSize(14);

        addLocalItem(labelLine);
    }

    private void addCenterLine(GeoPoint own, GeoPoint target) {
        List<GeoPoint> pts = new ArrayList<>();
        pts.add(own);
        pts.add(target);

        addLocalItem(makePolyline(
                pts,
                Color.WHITE,
                2.0,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
    }

    private void addArrowHead(GeoPoint target, double bearing) {
        double leg = 110.0;
        double back = normalizeDegrees(bearing + 180.0);

        List<GeoPoint> left = new ArrayList<>();
        left.add(target);
        left.add(GeoCalculations.pointAtDistance(
                target,
                back - 24.0,
                leg
        ));

        List<GeoPoint> right = new ArrayList<>();
        right.add(target);
        right.add(GeoCalculations.pointAtDistance(
                target,
                back + 24.0,
                leg
        ));

        addLocalItem(makePolyline(
                left,
                Color.WHITE,
                2.0,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
        addLocalItem(makePolyline(
                right,
                Color.WHITE,
                2.0,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
    }

    private void addTargetLabel(GeoPoint target, double bearing) {
        List<GeoPoint> pts = new ArrayList<>();
        pts.add(GeoCalculations.pointAtDistance(target, bearing, 35.0));
        pts.add(GeoCalculations.pointAtDistance(target, bearing, 250.0));

        Polyline label = makePolyline(
                pts,
                Color.argb(1, 255, 255, 255),
                0.1,
                Shape.BASIC_LINE_STYLE_SOLID
        );
        label.toggleMetaData("labels_on", true);
        label.setLineLabel("ZIEL");
        label.setLabelTextSize(16);
        addLocalItem(label);

        double d = 45.0;

        List<GeoPoint> cross1 = new ArrayList<>();
        cross1.add(pointFromAxis(target, bearing, -d, 0));
        cross1.add(pointFromAxis(target, bearing, d, 0));

        List<GeoPoint> cross2 = new ArrayList<>();
        cross2.add(pointFromAxis(target, bearing, 0, d));
        cross2.add(pointFromAxis(target, bearing, 0, -d));

        addLocalItem(makePolyline(
                cross1,
                COLOR_TARGET,
                2.7,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
        addLocalItem(makePolyline(
                cross2,
                COLOR_TARGET,
                2.7,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
    }

    /**
     * Exactly one central bracket pair, rotated 90 degrees compared with a
     * normal horizontal ")( ". The upper and lower curves open toward the
     * centerline.
     */
    private void addCenterBracket(GeoPoint own, double bearing) {
        final double anchor = 4000.0;
        final double halfWidth = 310.0;

        List<GeoPoint> upper = new ArrayList<>();
        List<GeoPoint> lower = new ArrayList<>();

        final int steps = 14;
        for (int i = 0; i <= steps; i++) {
            double t = -1.0 + 2.0 * i / steps;
            double along = anchor + t * halfWidth;

            // Ends farther away, center closer to the line.
            double offset = 105.0 + 175.0 * t * t;

            upper.add(pointFromAxis(own, bearing, along, offset));
            lower.add(pointFromAxis(own, bearing, along, -offset));
        }

        addLocalItem(makePolyline(
                upper,
                Color.WHITE,
                3.0,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
        addLocalItem(makePolyline(
                lower,
                Color.WHITE,
                3.0,
                Shape.BASIC_LINE_STYLE_SOLID
        ));
    }

    /**
     * Bearing above and distance below the centerline, directly after the
     * central bracket. The transparent carrier line keeps both labels aligned
     * to the selected bearing even when the map is rotated.
     */
    private void addBracketLabel(
            GeoPoint own,
            double bearing,
            double anchor,
            double crossOffset,
            String text) {

        List<GeoPoint> pts = new ArrayList<>();
        pts.add(pointFromAxis(
                own,
                bearing,
                anchor + 350.0,
                crossOffset
        ));
        pts.add(pointFromAxis(
                own,
                bearing,
                anchor + 900.0,
                crossOffset
        ));

        Polyline label = makePolyline(
                pts,
                Color.argb(1, 255, 255, 255),
                0.1,
                Shape.BASIC_LINE_STYLE_SOLID
        );
        label.toggleMetaData("labels_on", true);
        label.setLineLabel(text);
        label.setLabelTextSize(16);

        addLocalItem(label);
    }

    private Polyline makePolyline(
            List<GeoPoint> points,
            int color,
            double weight,
            int lineStyle) {

        Polyline line = new Polyline(UUID.randomUUID().toString());
        line.setPoints(wrap(points));
        line.setStrokeColor(color);
        line.setStrokeWeight(weight);
        line.setBasicLineStyle(lineStyle);
        line.setClickable(false);
        line.setEditable(false);
        line.setMovable(false);
        line.setMetaBoolean("nevercot", true);
        line.setMetaBoolean("addToObjList", false);
        return line;
    }

    private void addLocalItem(MapItem item) {
        item.setMetaBoolean("nevercot", true);
        item.setMetaBoolean("addToObjList", false);
        item.setClickable(false);
        item.setEditable(false);
        item.setMovable(false);
        overlayGroup.addItem(item);
    }

    private static GeoPointMetaData[] wrap(List<GeoPoint> points) {
        GeoPointMetaData[] wrapped = new GeoPointMetaData[points.size()];
        for (int i = 0; i < points.size(); i++) {
            wrapped[i] = GeoPointMetaData.wrap(points.get(i));
        }
        return wrapped;
    }

    /**
     * Local axis helper:
     * along = meters along target bearing.
     * cross > 0 = left of the target line.
     * cross < 0 = right of the target line.
     */
    private static GeoPoint pointFromAxis(
            GeoPoint origin,
            double bearing,
            double along,
            double cross) {

        GeoPoint onAxis = GeoCalculations.pointAtDistance(
                origin,
                bearing,
                along
        );

        if (Math.abs(cross) < 0.001) {
            return onAxis;
        }

        double crossBearing = normalizeDegrees(
                bearing + (cross > 0 ? -90.0 : 90.0)
        );

        return GeoCalculations.pointAtDistance(
                onAxis,
                crossBearing,
                Math.abs(cross)
        );
    }

    private static double toGridBearing(
            GeoPoint own,
            GeoPoint target,
            double trueBearing) {

        double convergence = ATAKUtilities.computeGridConvergence(own, target);
        if (Double.isNaN(convergence)) {
            convergence = 0.0;
        }

        return normalizeDegrees(trueBearing - convergence);
    }

    private static int degreesToMil(double degrees) {
        int mil = (int) Math.round(
                normalizeDegrees(degrees) * 6400.0 / 360.0
        );
        mil %= 6400;
        if (mil < 0) {
            mil += 6400;
        }
        return mil;
    }

    private static String formatRange(double meters) {
        int rounded = (int) Math.round(meters);

        if (rounded < 1000) {
            return rounded + " m";
        }

        if (rounded % 1000 == 0) {
            return String.format(
                    Locale.GERMANY,
                    "%.0f km",
                    meters / 1000.0
            );
        }

        return String.format(
                Locale.GERMANY,
                "%.1f km",
                meters / 1000.0
        );
    }

    private static String formatTargetDistance(double meters) {
        if (meters < 1000.0) {
            return String.format(
                    Locale.GERMANY,
                    "%.0f m",
                    meters
            );
        }

        return String.format(
                Locale.GERMANY,
                "%.1f km",
                meters / 1000.0
        );
    }

    private static boolean isUsable(GeoPoint point) {
        return point != null
                && !Double.isNaN(point.getLatitude())
                && !Double.isNaN(point.getLongitude());
    }

    private static double normalizeDegrees(double value) {
        double out = value % 360.0;
        if (out < 0.0) {
            out += 360.0;
        }
        return out;
    }
}
