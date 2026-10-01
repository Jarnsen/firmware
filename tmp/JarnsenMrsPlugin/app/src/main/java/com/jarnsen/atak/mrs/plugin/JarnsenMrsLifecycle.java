package com.jarnsen.atak.mrs.plugin;

import com.atak.plugins.impl.AbstractPlugin;
import com.atak.plugins.impl.PluginContextProvider;

import gov.tak.api.plugin.IServiceController;

public class JarnsenMrsLifecycle extends AbstractPlugin {

    public JarnsenMrsLifecycle(IServiceController serviceController) {
        super(
                serviceController,
                new JarnsenMrsPluginTool(
                        serviceController
                                .getService(PluginContextProvider.class)
                                .getPluginContext()),
                new JarnsenMrsMapComponent()
        );
    }
}
