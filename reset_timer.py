#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import json
import subprocess
import requests
from seleniumbase import SB

LOGIN_URL = "https://justrunmy.app/id/Account/Login"
DOMAIN    = "justrunmy.app"

EMAIL        = os.environ.get("ACC")
PASSWORD     = os.environ.get("ACC_PWD")
TG_BOT_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID   = os.environ.get("TG_ID")
APP_IDS_RAW  = os.environ.get("APP_IDS", "").strip()

if not EMAIL or not PASSWORD:
    print("致命错误：未找到 ACC 或 ACC_PWD 环境变量！")
    sys.exit(1)

if not APP_IDS_RAW:
    print("致命错误：未找到 APP_IDS 环境变量！")
    print("请配置 ID_x Secret，值为应用 ID，多个用逗号分隔，如: 37754,37755")
    sys.exit(1)

# 支持逗号/空格/换行分隔的多个应用 ID
APP_IDS = [i for i in re.split(r"[,\s]+", APP_IDS_RAW) if i.isdigit()]
if not APP_IDS:
    print(f"致命错误：APP_IDS 格式无效: {APP_IDS_RAW}")
    sys.exit(1)

def mask_ip(ip_str: str) -> str:
    try:
        data = json.loads(ip_str.strip())
        ip = data.get("ip", ip_str)
    except Exception:
        ip = ip_str.strip()

    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.*.*.{parts[3]}"
    return "*.*.*.*"

def dump_debug(sb, name: str):
    try:
        sb.save_screenshot(f"{name}.png")
    except Exception:
        pass
    try:
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(sb.get_page_source())
        print(f"  已保存调试文件: {name}.png / {name}.html")
    except Exception:
        pass

# ============================================================
#  Telegram 推送模块
# ============================================================
def send_tg_message(status_icon, status_text, time_left, app_name="未知应用"):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未配置 TG_TOKEN 或 TG_ID，跳过 Telegram 推送。")
        return

    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    if "[OK]" in status_icon:
        header = "✅ 续期成功"
    elif "[X]" in status_icon:
        header = "❌ 续期失败"
    elif "[!]" in status_icon:
        header = "⚠️ 续期异常"
    else:
        header = f"{status_icon} 续期通知"

    text = (
        "🔄 *JustRunMy* 自动续期报告\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{header}\n"
        f"🖥  应用：`{app_name}`\n"
        f"📋  状态：{status_text}\n"
        f"⏳  剩余：`{time_left}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐  时间：`{current_time_str}`"
    )

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("  Telegram 通知发送成功！")
        else:
            print(f"  Telegram 通知发送失败: {r.text}")
    except Exception as e:
        print(f"  Telegram 通知发送异常: {e}")

_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
(function(){
    return document.querySelector('input[name="cf-turnstile-response"]') !== null;
})()
"""

_SOLVED_JS = """
(function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
})()
"""

_COORDS_JS = """
(function(){
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.includes('cloudflare') || src.includes('turnstile') || src.includes('challenges')) {
            var r = iframes[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
        }
    }
    var inp = document.querySelector('input[name="cf-turnstile-response"]');
    if (inp) {
        var p = inp.parentElement;
        for (var j = 0; j < 5; j++) {
            if (!p) break;
            var r = p.getBoundingClientRect();
            if (r.width > 100 && r.height > 30)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2)};
            p = p.parentElement;
        }
    }
    return null;
})()
"""

_WININFO_JS = """
(function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""

# ============================================================
#  底层输入工具
# ============================================================
def js_fill_input(sb, selector: str, text: str):
    safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
    sb.execute_script(f"""
    (function(){{
        var el = document.querySelector('{selector}');
        if (!el) return;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {{
            nativeInputValueSetter.call(el, "{safe_text}");
        }} else {{
            el.value = "{safe_text}";
        }}
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """)

def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls],
                               capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]],
                               timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"],
                       timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _xdotool_click(x: int, y: int):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)],
                       timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")

def _click_turnstile(sb):
    try:
        coords = sb.execute_script(_COORDS_JS)
    except Exception as e:
        print(f"  获取 Turnstile 坐标失败: {e}")
        return
    if not coords:
        print("  无法定位 Turnstile 坐标")
        return
    try:
        wi = sb.execute_script(_WININFO_JS)
    except Exception:
        wi = {"sx": 0, "sy": 0, "oh": 800, "ih": 768}

    bar = wi["oh"] - wi["ih"]
    ax  = coords["cx"] + wi["sx"]
    ay  = coords["cy"] + wi["sy"] + bar
    print(f"  物理级点击 Turnstile ({ax}, {ay})")
    _xdotool_click(ax, ay)

# ============================================================
#  Blazor 渲染等待
# ============================================================
def wait_for_blazor(sb, check_js: str, timeout: int = 30, desc: str = "内容") -> bool:
    print(f"等待 Blazor 渲染{desc}（最长 {timeout}s）...")
    for i in range(timeout * 2):
        try:
            if sb.execute_script(check_js):
                print(f"  {desc}已渲染（耗时约 {i * 0.5:.1f}s）")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    print(f"  等待{desc}超时")
    return False

# ============================================================
#  人机验证处理
# ============================================================
def handle_turnstile(sb) -> bool:
    print("处理 Cloudflare Turnstile 验证...")
    time.sleep(2)

    if sb.execute_script(_SOLVED_JS):
        print("  已静默通过")
        return True

    for _ in range(3):
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.5)

    for attempt in range(6):
        if sb.execute_script(_SOLVED_JS):
            print(f"  Turnstile 通过（第 {attempt + 1} 次尝试）")
            return True
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.3)

        _click_turnstile(sb)

        for _ in range(8):
            time.sleep(0.5)
            if sb.execute_script(_SOLVED_JS):
                print(f"  Turnstile 通过（第 {attempt + 1} 次尝试）")
                return True
        print(f"  第 {attempt + 1} 次未通过，重试...")

    print("  Turnstile 6 次均失败")
    return False

# ============================================================
#  账户登录模块
# ============================================================
def login(sb) -> bool:
    print(f"打开登录页面: {LOGIN_URL}")
    sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=5)
    time.sleep(4)

    try:
        sb.wait_for_element('input[name="Email"]', timeout=15)
    except Exception:
        print("页面未加载出登录表单")
        dump_debug(sb, "login_load_fail")
        return False

    print("关闭可能的 Cookie 弹窗...")
    try:
        for btn in sb.find_elements("button"):
            if "Accept" in (btn.text or ""):
                btn.click()
                time.sleep(0.5)
                break
    except Exception:
        pass

    print("填写邮箱...")
    js_fill_input(sb, 'input[name="Email"]', EMAIL)
    time.sleep(0.3)

    print("填写密码...")
    js_fill_input(sb, 'input[name="Password"]', PASSWORD)
    time.sleep(1)

    if sb.execute_script(_EXISTS_JS):
        if not handle_turnstile(sb):
            print("登录界面的 Turnstile 验证失败")
            dump_debug(sb, "login_turnstile_fail")
            return False
    else:
        print("未检测到 Turnstile")

    print("敲击回车提交表单...")
    sb.press_keys('input[name="Password"]', '\n')

    print("等待登录跳转...")
    for _ in range(15):
        time.sleep(1)
        if sb.get_current_url().split('?')[0].lower() != LOGIN_URL.lower():
            break

    current = sb.get_current_url()
    if current.split('?')[0].lower() != LOGIN_URL.lower():
        print(f"登录成功！当前页面: {current}")
        return True

    print("登录失败，页面没有跳转。")
    dump_debug(sb, "login_failed")
    return False

# ============================================================
#  单应用续期
# ============================================================
def renew_app(sb, app_id: str) -> bool:
    detail_url = f"https://{DOMAIN}/panel/application/{app_id}"
    app_name = f"App-{app_id}"

    print("\n" + "=" * 50)
    print(f"   续期应用 ID: {app_id}")
    print("=" * 50)

    # ── 1. 直接打开应用详情页 ────────────────────────────────
    print(f"打开应用详情页: {detail_url}")
    sb.open(detail_url)
    time.sleep(3)

    if "/Account/Login" in sb.get_current_url():
        print("被重定向回登录页，会话已失效！")
        dump_debug(sb, f"renew_{app_id}_session_lost")
        send_tg_message("[X]", "续期失败(会话失效)", "未知", app_name)
        return False

    # ── 2. 等待 Blazor 渲染出 Reset Timer 按钮 ───────────────
    _reset_btn_js = """
    return (function(){
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++)
            if ((btns[i].textContent || '').includes('Reset Timer')) return true;
        return false;
    })()
    """
    if not wait_for_blazor(sb, _reset_btn_js, timeout=30, desc="Reset Timer 按钮"):
        print(f"当前 URL: {sb.get_current_url()}")
        dump_debug(sb, f"renew_{app_id}_reset_btn_not_found")
        send_tg_message("[X]", "续期失败(找不到按钮)", "未知", app_name)
        return False

    # ── 3. 尝试读取应用名称（可选，失败不影响流程）───────────
    try:
        name = sb.execute_script("""
            return (function(){
                var h = document.querySelector('h1, h2, h3');
                return h ? h.textContent.trim() : '';
            })()
        """)
        if name:
            app_name = name
            print(f"应用名称: {app_name}")
    except Exception:
        pass

    # ── 4. 点击 Reset Timer ──────────────────────────────────
    print("点击 Reset Timer 按钮...")
    try:
        sb.click('button:contains("Reset Timer")')
        time.sleep(3)
    except Exception as e:
        print(f"点击 Reset Timer 失败: {e}")
        dump_debug(sb, f"renew_{app_id}_reset_click_fail")
        send_tg_message("[X]", "续期失败(点击按钮失败)", "未知", app_name)
        return False

    # ── 5. 处理弹窗内 CF 验证 ────────────────────────────────
    print("检查续期弹窗内是否需要 CF 验证...")
    if sb.execute_script(_EXISTS_JS):
        if not handle_turnstile(sb):
            print("弹窗内的 Turnstile 验证失败")
            dump_debug(sb, f"renew_{app_id}_turnstile_fail")
            send_tg_message("[X]", "续期失败(人机验证未过)", "未知", app_name)
            return False
    else:
        print("弹窗内未检测到 Turnstile")

    # ── 6. 确认续期 ──────────────────────────────────────────
    print("点击 Just Reset 确认续期...")
    try:
        sb.click('button:contains("Just Reset")')
        print("提交续期请求，等待服务器处理...")
        time.sleep(5)
    except Exception as e:
        print(f"找不到 Just Reset 按钮: {e}")
        dump_debug(sb, f"renew_{app_id}_just_reset_not_found")
        send_tg_message("[X]", "续期失败(无法确认)", "未知", app_name)
        return False

    # ── 7. 验证倒计时 ────────────────────────────────────────
    print("验证最终倒计时状态...")
    try:
        sb.refresh()
        time.sleep(4)
        try:
            timer_text = sb.get_text('span.font-mono.text-xl')
        except Exception:
            timer_text = sb.execute_script("""
                return (function(){
                    var els = document.querySelectorAll('[class*="font-mono"]');
                    for (var i = 0; i < els.length; i++) {
                        var t = els[i].textContent.trim();
                        if (/day|hour|:/.test(t)) return t;
                    }
                    return '';
                })()
            """) or "未知"
        print(f"当前应用剩余时间: {timer_text}")

        if "2 days 23" in timer_text or "3 days" in timer_text:
            print("续期任务完成！")
            sb.save_screenshot(f"renew_{app_id}_success.png")
            send_tg_message("[OK]", "续期完成", timer_text, app_name)
            return True
        else:
            print("倒计时似乎没有重置到最高值，请人工检查截图。")
            dump_debug(sb, f"renew_{app_id}_warning")
            send_tg_message("[!]", "续期异常(请检查)", timer_text, app_name)
            return True
    except Exception as e:
        print(f"读取倒计时失败，但流程已执行完毕: {e}")
        dump_debug(sb, f"renew_{app_id}_timer_read_fail")
        send_tg_message("[!]", "读取剩余时间失败", "未知", app_name)
        return False

# ============================================================
#  脚本执行入口
# ============================================================
def main():
    print("=" * 50)
    print("   JustRunMy.app 自动登录与续期脚本")
    print("=" * 50)
    print(f"待续期应用 ID: {', '.join(APP_IDS)}")

    proxy_url_env = os.environ.get("PROXY_URL", "").strip()
    sb_kwargs = {"uc": True, "test": True, "headless": False}

    if proxy_url_env:
        local_proxy = "http://127.0.0.1:8080"
        print(f"检测到代理配置，挂载本地通道: {local_proxy}")
        sb_kwargs["proxy"] = local_proxy

    with SB(**sb_kwargs) as sb:
        print("浏览器已启动")
        try:
            sb.open("https://api.ipify.org/?format=json")
            raw = sb.get_text('body')
            print(f"当前出口 IP: {mask_ip(raw)}")
        except Exception:
            pass

        if not login(sb):
            print("\n登录环节失败，终止后续续期操作。")
            send_tg_message("[X]", "登录失败", "未知")
            sys.exit(1)

        results = {}
        for app_id in APP_IDS:
            try:
                results[app_id] = renew_app(sb, app_id)
            except Exception as e:
                print(f"应用 {app_id} 续期发生未捕获异常: {e}")
                results[app_id] = False
            time.sleep(2)

        print("\n" + "=" * 50)
        print("   续期结果汇总")
        for app_id, ok in results.items():
            print(f"   App {app_id}: {'成功' if ok else '失败'}")
        print("=" * 50)

        if not all(results.values()):
            sys.exit(1)

if __name__ == "__main__":
    main()
