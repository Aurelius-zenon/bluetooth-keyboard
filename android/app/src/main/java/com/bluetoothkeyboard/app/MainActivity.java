package com.bluetoothkeyboard.app;

import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;

import com.getcapacitor.BridgeActivity;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 原生壳：手势锁定。
 * 网页端在「锁定模式」开启时调用 window.NativeGestureGuard.setLock(true)，
 * 原生侧进入沉浸式全屏，并屏蔽左右边缘手势（系统返回/截屏），把触摸尽量留给 App。
 */
public class MainActivity extends BridgeActivity {

    private static final int EDGE_DP = 200;   // 系统对单边屏蔽区的上限
    private boolean gestureLock = false;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(GestureGuardPlugin.class);
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (getBridge() != null && getBridge().getWebView() != null) {
            getBridge().getWebView().addJavascriptInterface(new GestureGuard(), "NativeGestureGuard");
        }
        getWindow().getDecorView().addOnLayoutChangeListener(
                (v, l, t, r, b, ol, ot, or, ob) -> applyExclusion());
    }

    /** 供插件和 JS 接口共用 */
    public void setGestureLock(final boolean on) {
        runOnUiThread(() -> {
            gestureLock = on;
            if (on) applyImmersive();
            else showSystemBars();
            applyExclusion();
        });
    }

    /** 键盘页全屏锁定：只切换系统栏，不影响手势屏蔽 */
    public void setFullscreen(final boolean on) {
        runOnUiThread(() -> {
            if (on || gestureLock) applyImmersive();
            else showSystemBars();
        });
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus && gestureLock) applyImmersive();
    }

    private class GestureGuard {
        @JavascriptInterface
        public void setLock(final boolean on) {
            setGestureLock(on);
        }

        @JavascriptInterface
        public boolean isLocked() {
            return gestureLock;
        }
    }

    private void applyImmersive() {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = w.getInsetsController();
            if (c != null) {
                c.hide(WindowInsets.Type.systemBars());
                c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            w.getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    private void showSystemBars() {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = w.getInsetsController();
            if (c != null) c.show(WindowInsets.Type.systemBars());
        } else {
            w.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    /** 锁定期间屏蔽左右边缘手势区，减少系统抢占触摸；解锁立刻恢复 */
    private void applyExclusion() {
        if (Build.VERSION.SDK_INT < 29) return;
        View decor = getWindow().getDecorView();
        if (!gestureLock) {
            decor.setSystemGestureExclusionRects(Collections.emptyList());
            return;
        }
        int w = decor.getWidth();
        int h = decor.getHeight();
        if (w <= 0 || h <= 0) return;
        int edge = (int) (EDGE_DP * getResources().getDisplayMetrics().density);
        edge = Math.min(edge, Math.max(w / 3, 1));
        List<Rect> rects = new ArrayList<>();
        rects.add(new Rect(0, 0, edge, h));
        rects.add(new Rect(w - edge, 0, w, h));
        decor.setSystemGestureExclusionRects(rects);
    }
}
