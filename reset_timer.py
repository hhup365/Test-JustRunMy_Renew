#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import json
import random
import subprocess
import requests
from seleniumbase import SB

LOGIN_URL = "https://justrunmy.app/id/Account/Login"
PANEL_URL = "https://justrunmy.app/panel"
APPS_URL  = "https://justrunmy.app/panel/applications"
DOMAIN    = "justrunmy.app"

EMAIL        = os.environ.get("ACC")
PASSWORD     = os.environ.get("ACC_PWD")
TG_BOT_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID   = os.environ.get("TG_ID")

if not EMAIL or not PASSWORD:
    print("致命错误：未找到 ACC 或 ACC_PWD 环境变量！")
    print("请检查 GitHub Repository Secrets 是否配置正确。")
    sys.exit(1)

DYNAMIC_APP_NAME = "未知应用"

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
    """失败时同时保存截图和渲染后的 DOM"""
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
def send_tg_message(status_icon, status_text, time_left):
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
        f"🖥  应用：`{DYNAMIC_APP_NAME}`\n"
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

# 应用列表页查找应用链接
_FIND_APP_JS = """
(function(){
    var links = document.querySelectorAll('a[href*="/panel/application/"]');
    for (var i = 0; i < links.length; i++) {
        var href = links[i].getAttribute('href') || '';
        if (/\\/panel\\/application\\/\\d+/.test(href)) {
            var h3 = links[i].querySelector('h3');
            var name = h3 ? h3.textContent.trim() : links[i].textContent.trim().split('\\n')[0];
            return {href: href, name: name || '未知应用'};
        }
    }
    var h3s = document.querySelectorAll('h3');
    for (var j = 0; j < h3s.length; j++) {
        var t = h3s[j].textContent.trim();
        if (t.length > 0 && t.length < 100)
            return {href: null, name: t};
    }
    return null;
})()
"""

_RESET_BTN_JS = """
return (function(){
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++)
        if ((btns[i].textContent || '').includes('Reset Timer')) return true;
    return false;
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

def _xdotool_click(x: int, y: int, penetration_mode: bool = False):
    _activate_window()
    if penetration_mode:
        # 击穿模式：模拟人类鼠标变速平滑轨迹滑动
        print("  [击穿模式] 模拟人类鼠标平滑轨迹...")
        try:
            res = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                                 capture_output=True, text=True, timeout=2)
            lines = res.stdout.strip().split("\n")
            curr_x = int(lines[0].split("=")[1])
            curr_y = int(lines[1].split("=")[1])
        except Exception:
            curr_x, curr_y = 0, 0
        target_x = x + random.randint(-4, 4)
        target_y = y + random.randint(-4, 4)
        steps = random.randint(15, 25)
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)  # smoothstep 缓动
            next_x = int(curr_x + (target_x - curr_x) * t + random.randint(-1, 1))
            next_y = int(curr_y + (target_y - curr_y) * t + random.randint(-1, 1))
            subprocess.run(["xdotool", "mousemove", str(next_x), str(next_y)],
                           stderr=subprocess.DEVNULL)
            time.sleep(random.uniform(0.01, 0.02))
        subprocess.run(["xdotool", "mousemove", str(target_x), str(target_y)],
                       stderr=subprocess.DEVNULL)
        time.sleep(random.uniform(0.12, 0.25))
        subprocess.run(["xdotool", "mousedown", "1"], stderr=subprocess.DEVNULL)
        time.sleep(random.uniform(0.07, 0.16))
        subprocess.run(["xdotool", "mouseup", "1"], stderr=subprocess.DEVNULL)
        print(f"  击穿点击完成，落点: ({target_x}, {target_y})")
    else:
        rx = x + random.randint(-2, 2)
        ry = y + random.randint(-2, 2)
        print(f"  物理级点击 Turnstile ({rx}, {ry})")
        try:
            subprocess.run(["xdotool", "mousemove", "--sync", str(rx), str(ry)],
                           timeout=3, stderr=subprocess.DEVNULL)
            time.sleep(random.uniform(0.1, 0.2))
            subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
        except Exception:
            os.system(f"xdotool mousemove {rx} {ry} click 1 2>/dev/null")

def _click_turnstile(sb, penetration_mode: bool = False):
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
    _xdotool_click(ax, ay, penetration_mode=penetration_mode)

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

        # 第 3 次尝试起启用击穿模式（人类轨迹模拟）
        _click_turnstile(sb, penetration_mode=(attempt >= 2))

        for _ in range(8):
            time.sleep(random.uniform(0.4, 0.6))
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

    print("提交登录表单...")
    try:
        sb.click('button[type="submit"]')
    except Exception:
        sb.press_keys('input[name="Password"]', '\n')

    print("等待登录完成并验证会话...")
    time.sleep(5)

    # 关键修复：不能仅凭 URL 变化判断登录成功。
    # 直接访问控制面板并检查登录表单是否再次出现，确认认证 Cookie 真正生效。
    sb.open(PANEL_URL)
    time.sleep(5)

    current_url = sb.get_current_url()
    login_form_visible = sb.is_element_present('input[name="Email"]')
    if "/id/Account/Login" not in current_url and not login_form_visible:
        print(f"登录成功，会话验证通过！当前页面: {current_url}")
        return True

    print(f"登录失败或会话未生效，当前页面: {current_url}")
    dump_debug(sb, "login_failed")
    return False

def check_session(sb) -> bool:
    """检查当前页面是否被重定向回登录页"""
    url = sb.get_current_url()
    if "/id/Account/Login" in url or sb.is_element_present('input[name="Email"]'):
        print(f"会话已失效，被重定向: {url}")
        return False
    return True

# ============================================================
#  自动续期模块
# ============================================================
def renew(sb) -> bool:
    global DYNAMIC_APP_NAME

    print("\n" + "=" * 50)
    print("   开始自动续期流程")
    print("=" * 50)

    # ── 1. 进入应用列表页 ────────────────────────────────────
    print(f"进入应用列表页: {APPS_URL}")
    sb.open(APPS_URL)
    time.sleep(3)

    if not check_session(sb):
        dump_debug(sb, "renew_session_lost")
        send_tg_message("[X]", "续期失败(会话失效)", "未知")
        return False

    # ── 2. 等待 Blazor 渲染出应用并进入详情页 ───────────────
    if not wait_for_blazor(sb, "return " + _FIND_APP_JS + " !== null",
                           timeout=30, desc="应用列表"):
        print(f"当前 URL: {sb.get_current_url()}")
        dump_debug(sb, "renew_app_not_found")
        send_tg_message("[X]", "续期失败(找不到应用)", "未知")
        return False

    app_info = sb.execute_script("return " + _FIND_APP_JS)
    DYNAMIC_APP_NAME = app_info.get("name") or "未知应用"
    app_href = app_info.get("href")
    print(f"成功抓取到应用: {DYNAMIC_APP_NAME} -> {app_href}")

    if app_href:
        detail_url = app_href if app_href.startswith("http") else f"https://{DOMAIN}{app_href}"
        print(f"打开应用详情页: {detail_url}")
        sb.open(detail_url)
    else:
        print("未找到链接，尝试点击应用卡片...")
        try:
            sb.click('a[href*="/panel/application/"]')
        except Exception:
            sb.click('h3')
    time.sleep(3)

    if not check_session(sb):
        dump_debug(sb, "renew_detail_session_lost")
        send_tg_message("[X]", "续期失败(会话失效)", "未知")
        return False

    if not re.search(r"/panel/application/\d+", sb.get_current_url()):
        print(f"未能进入应用详情页，当前 URL: {sb.get_current_url()}")
        dump_debug(sb, "renew_detail_fail")
        send_tg_message("[X]", "续期失败(无法进入详情页)", "未知")
        return False
    print(f"成功进入应用详情页: {sb.get_current_url()}")

    # ── 3. 等待并点击 Reset Timer ────────────────────────────
    if not wait_for_blazor(sb, _RESET_BTN_JS, timeout=30, desc="Reset Timer 按钮"):
        dump_debug(sb, "renew_reset_btn_not_found")
        send_tg_message("[X]", "续期失败(找不到按钮)", "未知")
        return False

    print("点击 Reset Timer 按钮...")
    try:
        sb.click('button:contains("Reset Timer")')
        time.sleep(3)
    except Exception as e:
        print(f"点击 Reset Timer 失败: {e}")
        dump_debug(sb, "renew_reset_click_fail")
        send_tg_message("[X]", "续期失败(点击按钮失败)", "未知")
        return False

    # ── 4. 处理弹窗内 CF 验证 ────────────────────────────────
    print("检查续期弹窗内是否需要 CF 验证...")
    if sb.execute_script(_EXISTS_JS):
        if not handle_turnstile(sb):
            print("弹窗内的 Turnstile 验证失败")
            dump_debug(sb, "renew_turnstile_fail")
            send_tg_message("[X]", "续期失败(人机验证未过)", "未知")
            return False
    else:
        print("弹窗内未检测到 Turnstile")

    # ── 5. 确认续期 ──────────────────────────────────────────
    print("点击 Just Reset 确认续期...")
    try:
        sb.click('button:contains("Just Reset")')
        print("提交续期请求，等待服务器处理...")
        time.sleep(5)
    except Exception as e:
        print(f"找不到 Just Reset 按钮: {e}")
        dump_debug(sb, "renew_just_reset_not_found")
        send_tg_message("[X]", "续期失败(无法确认)", "未知")
        return False

    # ── 6. 验证倒计时 ────────────────────────────────────────
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
            sb.save_screenshot("renew_success.png")
            send_tg_message("[OK]", "续期完成", timer_text)
            return True
        else:
            print("倒计时似乎没有重置到最高值，请人工检查截图。")
            dump_debug(sb, "renew_warning")
            send_tg_message("[!]", "续期异常(请检查)", timer_text)
            return True
    except Exception as e:
        print(f"读取倒计时失败，但流程已执行完毕: {e}")
        dump_debug(sb, "renew_timer_read_fail")
        send_tg_message("[!]", "读取剩余时间失败", "未知")
        return False

# ============================================================
#  脚本执行入口
# ============================================================
def main():
    print("=" * 50)
    print("   JustRunMy.app 自动登录与续期脚本")
    print("=" * 50)

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

        if login(sb):
            if not renew(sb):
                sys.exit(1)
        else:
            print("\n登录环节失败，终止后续续期操作。")
            send_tg_message("[X]", "登录失败", "未知")
            sys.exit(1)

if __name__ == "__main__":
    main()
