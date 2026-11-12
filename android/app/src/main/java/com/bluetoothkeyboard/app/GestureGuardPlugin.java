package com.bluetoothkeyboard.app;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * 只负责键盘页的全屏锁定；手势全部由网页端解释，不涉及系统手势屏蔽。
 */
@CapacitorPlugin(name = "GestureGuard")
public class GestureGuardPlugin extends Plugin {

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
