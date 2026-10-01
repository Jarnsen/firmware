package com.jarnsen.atak.mrs.plugin;

import android.content.Context;

import com.atak.plugins.impl.AbstractPluginTool;

public class JarnsenMrsPluginTool extends AbstractPluginTool {

    public static final String ACTION_SHOW =
            "com.jarnsen.atak.mrs.SHOW_JARNSEN_MRS";

    public JarnsenMrsPluginTool(Context context) {
        super(
                context,
                context.getString(R.string.app_name),
                context.getString(R.string.app_desc),
                context.getResources().getDrawable(R.drawable.ic_launcher),
                ACTION_SHOW
        );
    }
}
