package com.jarnsen.atak.mrs.plugin;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import com.atakmap.android.ipc.AtakBroadcast;
import com.atakmap.android.maps.AbstractMapComponent;
import com.atakmap.android.maps.DefaultMapGroup;
import com.atakmap.android.maps.MapGroup;
import com.atakmap.android.maps.MapView;
import com.atakmap.android.toolbar.ToolManagerBroadcastReceiver;
import com.atakmap.coremap.log.Log;

public class JarnsenMrsMapComponent extends AbstractMapComponent {

    private static final String TAG = "JarnsenMrsComponent";

    private MapGroup overlayGroup;
    private JarnsenMrsSectorTool sectorTool;

    private final BroadcastReceiver showReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!JarnsenMrsPluginTool.ACTION_SHOW.equals(intent.getAction())) {
                return;
            }

            ToolManagerBroadcastReceiver.getInstance().startTool(
                    JarnsenMrsSectorTool.TOOL_IDENTIFIER,
                    new Bundle()
            );
        }
    };

    @Override
    public void onCreate(Context context, Intent intent, MapView view) {
        context.setTheme(R.style.ATAKPluginTheme);

        overlayGroup = new DefaultMapGroup("Jarnsen Mrs Plugin");
        overlayGroup.setMetaBoolean("permaGroup", false);
        view.getRootGroup().addGroup(overlayGroup);

        sectorTool = new JarnsenMrsSectorTool(view, overlayGroup);

        AtakBroadcast.DocumentedIntentFilter filter =
                new AtakBroadcast.DocumentedIntentFilter();
        filter.addAction(
                JarnsenMrsPluginTool.ACTION_SHOW,
                "Start Jarnsen Mrs target selection"
        );
        AtakBroadcast.getInstance().registerReceiver(showReceiver, filter);

        Log.d(TAG, "Jarnsen Mrs Plugin loaded");
    }

    @Override
    protected void onDestroyImpl(Context context, MapView view) {
        try {
            AtakBroadcast.getInstance().unregisterReceiver(showReceiver);
        } catch (Exception ignored) {
        }

        if (sectorTool != null) {
            sectorTool.dispose();
            sectorTool = null;
        }

        if (overlayGroup != null) {
            overlayGroup.clearItems();
            if (overlayGroup.getParentGroup() != null) {
                overlayGroup.getParentGroup().removeGroup(overlayGroup);
            }
            overlayGroup = null;
        }

        Log.d(TAG, "Jarnsen Mrs Plugin unloaded");
    }

    @Override
    public void onStart(Context context, MapView view) {
    }

    @Override
    public void onStop(Context context, MapView view) {
    }

    @Override
    public void onPause(Context context, MapView view) {
    }

    @Override
    public void onResume(Context context, MapView view) {
    }
}
