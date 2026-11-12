package com.bluetoothkeyboard.app;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * 手势锁定插件：网页端 Capacitor.Plugins.GestureGuard.setLock({ on: true })
 */
@CapacitorPlugin(name = "GestureGuard")
public class GestureGuardPlugin extends Plugin {

    @PluginMethod
    public void setLock(PluginCall call) {
        boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
        MainActivity activity = (MainActivity) getActivity();
        if (activity != null) activity.setGestureLock(on);
        JSObject ret = new JSObject();
        ret.put("on", on);
        call.resolve(ret);
    }

    @PluginMethod
    public void setFullscreen(PluginCall call) {
        boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
        MainActivity activity = (MainActivity) getActivity();
        if (activity != null) activity.setFullscreen(on);
        JSObject ret = new JSObject();
        ret.put("on", on);
        call.resolve(ret);
    }
}
