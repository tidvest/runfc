import os, re, logging, random, base64, json, math, time
from pathlib import Path
from datetime import datetime, timedelta
import ddddocr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

EMAIL    = os.environ["EMAIL"]
PASSWORD = os.environ["PASSWORD"]
BASE_URL     = "https://run.freecloud.ltd"
LOGIN_URL    = f"{BASE_URL}/login"
SERVICE_PAGE = f"{BASE_URL}/service?groupid=305"
SIGN_PAGE    = f"{BASE_URL}/addons?_plugin=5&controller=index&action=index"

# 代理：Xray 本地 SOCKS5
PROXY_SERVER = "socks5://127.0.0.1:10808"

SCREENSHOT_DIR = Path("./screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ---------- WxPusher 推送 ----------
WXPUSHER_TOKEN = os.environ.get("WXPUSHER_TOKEN", "")
WXPUSHER_UID   = os.environ.get("WXPUSHER_UID", "")

def wxpush(content: str):
    if not WXPUSHER_TOKEN or not WXPUSHER_UID:
        log.warning("📨 WXPUSHER_TOKEN 或 WXPUSHER_UID 未配置，跳过推送")
        return
    import urllib.request
    payload = json.dumps({
        "appToken": WXPUSHER_TOKEN,
        "content":  content,
        "contentType": 1,
        "uids": [WXPUSHER_UID],
    }).encode()
    try:
        req = urllib.request.Request(
            "https://wxpusher.zjiecode.com/api/send/message",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("success"):
                log.info("📨 WxPusher 推送成功")
            else:
                log.warning(f"📨 WxPusher 推送失败: {result}")
    except Exception as e:
        log.warning(f"📨 WxPusher 推送异常: {e}")

ocr = ddddocr.DdddOcr(beta=True, show_ad=False)

# ---------- 工具函数 ----------
def take_screenshot(page, name):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(SCREENSHOT_DIR / f"{ts}_{name}.png")
        page.screenshot(path=path, full_page=False)
        log.info(f"📸 截图: {path}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

def get_text(page) -> str:
    try:
        return page.inner_text("body") or ""
    except:
        return ""

def human_delay(min_s=0.3, max_s=0.8):
    time.sleep(random.uniform(min_s, max_s))

def wait_for_url_contains(page, keyword, timeout=10) -> bool:
    try:
        page.wait_for_url(f"**{keyword}**", timeout=timeout * 1000)
        return True
    except:
        return keyword in page.url

def js_click(page, selector, desc="") -> bool:
    try:
        result = page.evaluate(f"""() => {{
            var el = document.querySelector('{selector}');
            if (el) {{ el.click(); return true; }}
            return false;
        }}""")
        if result:
            log.info(f"JS 点击成功: {desc or selector}")
            return True
    except Exception as e:
        log.warning(f"JS 点击失败 [{desc}]: {e}")
    return False

def js_click_by_text(page, tag, text, desc="") -> bool:
    """按钮没有稳定 selector 时，按可见文字匹配并用 JS 点击，绕开 CloakBrowser human click"""
    try:
        result = page.evaluate(f"""() => {{
            var els = document.querySelectorAll('{tag}');
            for (var el of els) {{
                if (el.innerText && el.innerText.trim().includes('{text}') && el.offsetParent !== null) {{
                    el.click();
                    return true;
                }}
            }}
            return false;
        }}""")
        if result:
            log.info(f"JS 点击成功: {desc or text}")
            return True
        log.warning(f"JS 点击未找到元素 [{desc or text}]")
    except Exception as e:
        log.warning(f"JS 点击失败 [{desc or text}]: {e}")
    return False

def js_focus_and_type(page, selector, text, desc="") -> bool:
    """focus() 是 DOM 原生聚焦（不像 js_click 的 .click() 不一定给真实焦点），
    配合 insert_text（CDP 直接注入，未被 CloakBrowser patch）安全输入文字"""
    try:
        focused = page.evaluate(f"""() => {{
            var el = document.querySelector('{selector}');
            if (el) {{ el.focus(); el.value = ''; return true; }}
            return false;
        }}""")
        if not focused:
            log.warning(f"聚焦失败 [{desc or selector}]")
            return False
        page.keyboard.insert_text(text)
        log.info(f"已输入 [{desc or selector}]: {text}")
        return True
    except Exception as e:
        log.warning(f"输入失败 [{desc or selector}]: {e}")
        return False

def click_layui_ok(page, desc="确定") -> bool:
    """layui 弹窗确定是 <a class='layui-layer-btn0'>，不是 <button>"""
    result = page.evaluate("""() => {
        var a = document.querySelector('a.layui-layer-btn0');
        if (a) { a.click(); return 'layui-a'; }
        var btns = document.querySelectorAll('button');
        for (var b of btns) {
            if (b.innerText.trim() === '确定' && b.offsetParent !== null) {
                b.click(); return 'button';
            }
        }
        return null;
    }""")
    log.info(f"点击{desc}: {result}")
    return bool(result)

def read_expiry_from_service_page(page):
    result = page.evaluate("""() => {
        var tables = document.querySelectorAll('table');
        for (var tbl of tables) {
            var headers = tbl.querySelectorAll('th');
            var colIdx = -1;
            for (var i = 0; i < headers.length; i++) {
                if (headers[i].innerText.indexOf('到期') !== -1) { colIdx = i; break; }
            }
            if (colIdx >= 0) {
                var rows = tbl.querySelectorAll('tbody tr');
                for (var row of rows) {
                    var tds = row.querySelectorAll('td');
                    if (tds[colIdx]) {
                        var t = tds[colIdx].innerText.trim();
                        var m = t.match(/20\\d\\d-\\d{2}-\\d{2}/);
                        if (m) return m[0];
                    }
                }
            }
        }
        var rows = document.querySelectorAll('tr');
        for (var row of rows) {
            var rowText = row.innerText || '';
            if (rowText.indexOf('已激活') !== -1 || rowText.indexOf('Active') !== -1) {
                var m = rowText.match(/20\\d\\d-\\d{2}-\\d{2}/);
                if (m) return m[0];
            }
        }
        return null;
    }""")
    return str(result) if result else None

# ---------- Cloudflare 等待 ----------
def is_cf_blocked(page) -> bool:
    # 优先用 DOM 标记判断：不受页面语言影响（CF 验证页会按访问者地区
    # 自动切换语言，比如这次 GitHub Actions runner 被识别成荷兰地区，
    # 显示的是荷兰语 "Beveiliging wordt geverifieerd"，原来只认英文
    # "verify you are human" / "security" 的文本判断会完全失效）
    try:
        has_widget = page.evaluate("""() => {
            return !!(
                document.querySelector('iframe[src*="challenges.cloudflare.com"]') ||
                document.querySelector('input[name="cf-turnstile-response"]') ||
                document.querySelector('.cf-turnstile') ||
                document.querySelector('#challenge-stage') ||
                document.querySelector('#cf-wrapper')
            );
        }""")
        if has_widget:
            return True
    except Exception:
        pass

    try:
        body = get_text(page).lower()
        if "verify you are human" in body:
            return True
        if "cloudflare" in body and "security" in body:
            return True
        # "Ray ID:" 在任何语言的 CF 页面上都不会被翻译，是最可靠的兜底信号
        if "ray id" in body:
            return True
        return False
    except Exception:
        return False

def wait_cf_pass(page, timeout=45) -> bool:
    log.info("等待 Cloudflare 验证自动通过...")
    for i in range(timeout):
        if not is_cf_blocked(page):
            log.info(f"✅ Cloudflare 验证通过（{i}s）")
            return True
        if i % 5 == 0 and i > 0:
            log.info(f"  CF 等待中... {i}s")
        time.sleep(1)
    log.error(f"Cloudflare 验证超时（{timeout}s）")
    return False

# ---------- CF 复选框点击（移植自 zyno 的 click_turnstile_checkbox） ----------
def click_cf_checkbox(page, timeout=45) -> bool:
    """
    CF Turnstile 点击：
      - 枚举 page.frames 找 CF iframe（CDP层面，不受 shadow-root 限制）
      - 找到后等 frame 稳定（连续2次 bounding_box 一致），再点击
        （CF 初始化时会销毁旧 iframe 挂新的，立刻拿到的是旧 frame，
          等稳定后再点才是真正可点的那个）
      - 点击后等登录页邮箱 input 出现（最多 timeout 秒）
    """

    def dump_frames(label: str):
        try:
            frames = page.frames
            log.info(f"[诊断/{label}] 当前共 {len(frames)} 个 frame：")
            for i, f in enumerate(frames):
                log.info(f"  [{i}] {(f.url or 'about:blank')[:150]}")
        except Exception as e:
            log.warning(f"[诊断/{label}] dump_frames 失败: {e}")

    def login_page_ready() -> bool:
        try:
            return page.locator(
                'input[name="email"], input[placeholder="请输入邮箱地址"]'
            ).first.is_visible(timeout=500)
        except Exception:
            return False

    def find_stable_cf_frame(stable_timeout=12):
        """
        持续枚举 page.frames，找到 CF frame 后验证其 bounding_box 连续
        2次非 None 且位置一致，确认 iframe 已稳定挂载再返回。
        CF Turnstile 初始化会销毁旧 iframe 挂新的，tick=0 找到的往往是
        正在被替换的旧 frame，等稳定后才是真正可点的那个。
        """
        deadline = time.time() + stable_timeout
        while time.time() < deadline:
            cf_frame = None
            for f in page.frames:
                if "challenges.cloudflare.com" in (f.url or ""):
                    cf_frame = f
                    break
            if not cf_frame:
                time.sleep(0.3)
                continue
            # 取第一次 bounding_box
            try:
                box1 = cf_frame.frame_element().bounding_box()
            except Exception as e:
                log.warning(f"  [稳定检测] frame_element 失败: {e}，继续等...")
                time.sleep(0.3)
                continue
            if not box1:
                log.warning("  [稳定检测] box1=None，iframe 未渲染，继续等...")
                time.sleep(0.3)
                continue
            # 等 300ms 再取第二次，确认没被替换
            time.sleep(0.3)
            try:
                box2 = cf_frame.frame_element().bounding_box()
            except Exception as e:
                log.warning(f"  [稳定检测] 二次确认 frame_element 失败: {e}，继续等...")
                time.sleep(0.3)
                continue
            if box2 and abs(box2["y"] - box1["y"]) < 5:
                log.info(f"  ✅ CF frame 稳定，bounding_box={box2}")
                return cf_frame, box2
            log.warning(f"  [稳定检测] 位置漂移 box1={box1} box2={box2}，继续等...")
            time.sleep(0.3)
        return None, None

    # ── 阶段1：找稳定的 CF frame ────────────────────────────────
    log.info("【CF 阶段1】查找稳定 CF iframe（最多 12s）...")
    dump_frames("阶段1开始")
    cf_frame, box = find_stable_cf_frame(stable_timeout=12)

    # ── 阶段2：坐标点击 ──────────────────────────────────────────
    clicked = False
    if cf_frame and box:
        x = box["x"] + 25
        y = box["y"] + box["height"] / 2
        try:
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.2, 0.4))
            page.mouse.click(x, y)
            log.info(f"  ✅ 坐标点击 ({x:.0f}, {y:.0f})")
            clicked = True
        except Exception as e:
            log.warning(f"  坐标点击失败: {e}")
    else:
        log.warning("【CF 阶段1】未找到稳定 CF frame")
        dump_frames("枚举失败")

    if not clicked:
        log.error("【CF 阶段2】坐标点击失败")
        take_screenshot(page, "cf_checkbox_give_up")
        return False

    take_screenshot(page, "cf_checkbox_clicked")

    # ── 阶段3：等待登录页就绪（最多 timeout 秒）────────────────
    log.info(f"【CF 阶段3】等待登录页出现（最多 {timeout}s）...")
    for i in range(timeout * 2):
        if login_page_ready():
            log.info(f"  ✅ CF 验证通过，登录页已就绪（{i * 0.5:.1f}s）")
            return True
        if i % 10 == 0 and i > 0:
            log.info(f"  等待中... {i * 0.5:.0f}s")
            take_screenshot(page, f"cf_wait_{i}")
        time.sleep(0.5)

    log.error(f"【CF 阶段3】等待 {timeout}s 后登录页仍未出现")
    take_screenshot(page, "cf_checkbox_give_up")
    return False

def wait_for_page_settle(page, settle_timeout=8) -> None:
    """
    domcontentloaded 之后 CF 验证页的 iframe 还没渲染，
    轮询最多 settle_timeout 秒，等到 body 有实质内容（不是空白）或
    CF 标记出现为止。这样后续的 is_cf_blocked() / wait_for_selector 才有意义。
    """
    deadline = time.time() + settle_timeout
    while time.time() < deadline:
        try:
            body = page.inner_text("body") or ""
        except Exception:
            body = ""
        # 1) CF 验证框已出现 → 停止等待，让调用方来处理
        # 2) 真实页面内容已出现（比如 <input> 或足够多文字）→ 也停止
        if is_cf_blocked(page):
            log.info("  页面已稳定（CF 验证框就绪）")
            return
        if len(body.strip()) > 100:
            log.info("  页面已稳定（内容就绪）")
            return
        time.sleep(0.5)
    log.info("  页面稳定等待超时，继续执行...")

def navigate(page, url, timeout=60) -> bool:
    log.info(f"导航到: {url}")
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        log.warning(f"goto 超时/异常: {e}，继续等待...")

    # domcontentloaded 之后 CF iframe 还没渲染，先等页面稳定
    wait_for_page_settle(page, settle_timeout=12)

    if not is_cf_blocked(page):
        return True

    # 给被动自动过留足时间——这种站点常见的是"非交互式 Managed Challenge"
    # （没有可点击的复选框，纯后台 JS/指纹校验），10s 经常等不到它跑完，
    # 实测一般需要 20~35s 才会出现"Verificatie geslaagd"。40s 留够余量，
    # wait_cf_pass 内部是逐秒轮询，提前过了就立刻返回，不会真的傻等 40s
    if wait_cf_pass(page, timeout=40):
        return True

    # 被动等了 40s 还没过，大概率是真的需要交互的 Turnstile checkbox，
    # 这才进入点击逻辑（在当前页面反复尝试点击复选框，全程不重新 goto/reload）
    log.info("CF 被动等待未通过，开始在当前页面尝试点击复选框...")
    if click_cf_checkbox(page, timeout=timeout):
        return True

    # 多次点击仍未通过，才做最后一次刷新兜底（而不是退回上层重新整个登录流程）
    log.info("多次点击仍未通过，刷新页面做最后一次兜底...")
    try:
        page.reload(wait_until="domcontentloaded", timeout=30000)
    except:
        pass
    if not is_cf_blocked(page):
        return True
    if wait_cf_pass(page, timeout=40):
        return True
    return click_cf_checkbox(page, timeout=30)

# ---------- 验证码 ----------
def fill_captcha(page) -> str:
    for _ in range(3):
        cap_img = None
        try:
            loc = page.locator("#allow_login_email_captcha").first
            if loc.is_visible(timeout=3000):
                cap_img = loc
        except:
            pass
        if cap_img is None:
            try:
                loc = page.locator("img[alt='验证码']").first
                if loc.is_visible(timeout=3000):
                    cap_img = loc
            except:
                pass
        if cap_img:
            src = cap_img.get_attribute("src") or ""
            if src.startswith("data:image"):
                b64 = src.split(",", 1)[1]
                img_bytes = base64.b64decode(b64)
                raw = ocr.classification(img_bytes)
                code = re.sub(r'[^0-9]', '', raw)
                log.info(f"识别验证码: {code}")
                page.evaluate(f"""
                    (function() {{
                        var input =
                            document.querySelector('#captcha_allow_login_email_captcha') ||
                            document.querySelector('input[name="captcha"]') ||
                            document.querySelector('input[placeholder*="验证码"]');
                        if (input) {{
                            input.focus();
                            input.value = '{code}';
                            input.dispatchEvent(new Event('input', {{bubbles:true}}));
                            input.dispatchEvent(new Event('change', {{bubbles:true}}));
                        }}
                    }})()
                """)
                return code
        time.sleep(1)
    return ""

# ---------- 登录 ----------
def login(page, max_retries=3) -> bool:
    for attempt in range(1, max_retries + 1):
        log.info(f"登录 {attempt}/{max_retries}")
        if not navigate(page, LOGIN_URL):
            log.error("CF 验证失败，重试登录")
            continue

        try:
            page.wait_for_selector(
                'input[name="email"], input[placeholder="请输入邮箱地址"]',
                timeout=10000
            )
        except:
            log.warning("找不到邮箱输入框，重试")
            take_screenshot(page, f"login_fail_{attempt}")
            continue

        # CloakBrowser patch了 click/fill/type/keyboard.type，CF后viewport丢失全崩
        # focus() 确保真实焦点，insert_text 是CDP直接注入，不走human scroll
        page.evaluate("document.querySelector(\"input[name='email']\").focus()")
        page.evaluate("document.querySelector(\"input[name='email']\").value = ''")
        page.keyboard.insert_text(EMAIL)
        human_delay()

        page.evaluate("document.querySelector(\"input[name='password']\").focus()")
        page.evaluate("document.querySelector(\"input[name='password']\").value = ''")
        page.keyboard.insert_text(PASSWORD)
        human_delay()

        captcha = fill_captcha(page)
        if not captcha:
            log.warning("验证码识别失败，重试")
            continue

        # 登录按钮也用 js_click，避免 human click 崩
        if not js_click(page, "button.btn.btn-primary", "登录按钮"):
            js_click(page, "button[type='submit']", "登录按钮submit")
        log.info("已点击登录，检查跳转...")

        if wait_for_url_contains(page, "/clientarea", 10):
            log.info("✅ 登录成功")
            take_screenshot(page, "02_login_success")
            return True

        log.warning("登录后未跳转，重试")
        take_screenshot(page, f"login_no_redirect_{attempt}")

    return False

# ---------- 签到 ----------
def sign(page):
    log.info("前往签到页...")
    if not navigate(page, SIGN_PAGE):
        log.warning("签到页 CF 验证失败")
        return None

    for _ in range(10):
        body = get_text(page)
        if "我要签到" in body or "已签到" in body or "今日已" in body:
            break
        time.sleep(1)

    body = get_text(page)
    if "已签到" in body or "今日已" in body:
        log.info("今日已签到")
        take_screenshot(page, "02_already_signed")
        bal = re.search(r'账户余额剩余\s*([\d.]+)\s*积分', body)
        return bal.group(1) if bal else None

    if "我要签到" not in body:
        log.warning(f"未找到签到按钮, 片段: {body[:200]}")
        take_screenshot(page, "02_sign_check")
        return None

    js_click_by_text(page, "button", "我要签到", "我要签到按钮")
    log.info("已点击'我要签到'")
    time.sleep(1.5)

    body = get_text(page)
    match = re.search(r'请计算[：:]\s*(\d+)\s*([+\-*/])\s*(\d+)', body)
    if match:
        a, op, b = int(match[1]), match[2], int(match[3])
        if   op == '+': result = a + b
        elif op == '-': result = a - b
        elif op == '*': result = a * b
        elif op == '/': result = a / b if b != 0 else 0
        else:           result = 0
        result_str = (
            str(int(result)) if result == int(result)
            else f"{math.floor(result * 100 + 0.5) / 100:.2f}".rstrip("0").rstrip(".")
        )
        log.info(f"数学题: {a} {op} {b} = {result_str}")

        js_focus_and_type(page, 'input[placeholder="请输入答案"]', result_str, "答案输入框")
        js_click_by_text(page, "button", "验证答案", "验证答案按钮")
        log.info("已点击验证答案，等待弹窗...")
        time.sleep(2)

        # 弹窗1：验证成功 → 点确定
        for _ in range(12):
            body = get_text(page)
            if "验证成功" in body or "继续签到" in body:
                log.info("检测到验证成功弹窗，点击确定...")
                click_layui_ok(page, "验证弹窗确定")
                time.sleep(1.5)
                break
            time.sleep(0.5)

        # 弹窗2：签到成功 → 点确定
        for _ in range(12):
            body = get_text(page)
            if "签到成功" in body:
                log.info("检测到签到成功弹窗，点击确定...")
                click_layui_ok(page, "签到成功确定")
                time.sleep(1.5)
                break
            time.sleep(0.5)

    log.info("签到流程完成")
    take_screenshot(page, "03_sign_complete")

    # 刷新签到页，读取最新积分
    time.sleep(1)
    page.goto(SIGN_PAGE, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)
    body = get_text(page)
    bal = re.search(r'账户余额剩余\s*([\d.]+)\s*积分', body)
    balance = bal.group(1) if bal else None
    log.info(f"签到后最新积分: {balance}")
    return balance

# ---------- 续费 ----------
def renew(page):
    log.info("检查续费...")
    page.goto(SERVICE_PAGE, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    take_screenshot(page, "03b_service_page")

    expiry_str = read_expiry_from_service_page(page)
    if not expiry_str:
        body = get_text(page)
        m = re.search(r'到期时间[：:\s]*(\d{4}-\d{2}-\d{2})', body)
        if not m:
            m = re.search(r'(\d{4}-\d{2}-\d{2})', body)
        expiry_str = m.group(1) if m else None

    if not expiry_str:
        log.info("未找到到期日")
        return False, None, None

    expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
    remain = (expiry - datetime.now()).days
    log.info(f"到期: {expiry_str}，剩余 {remain} 天")

    # 到期前两天才续费（与原 runfreecloud 逻辑一致）
    if remain > 2:
        log.info(f"距到期还有 {remain} 天，暂不续费")
        return False, expiry_str, remain

    log.info(f"剩余 {remain} 天，开始续费...")

    # 第1步：勾选 checkbox
    js_click(page, "input#customCheck", "全选checkbox") or \
        js_click(page, "input.custom-control-input", "行checkbox")
    time.sleep(1)
    take_screenshot(page, "04a_checked")

    # 第2步：点续费按钮
    if not (js_click(page, "button#readBtn", "续费按钮") or
            js_click(page, "button.btn-outline-primary", "续费按钮outline")):
        log.warning("找不到续费按钮，放弃")
        return False, expiry_str, remain
    time.sleep(3)
    take_screenshot(page, "04b_after_renew_click")

    # 第3步：批量续费页 → 立即续费
    js_click(page, "button.xfSubmit", "立即续费") or \
        js_click(page, "button[type='submit']", "立即续费 submit")
    time.sleep(3)
    take_screenshot(page, "04c_after_xfsubmit")

    # 第4步：账单页 → 立即支付
    js_click(page, "button#payamount", "立即支付") or \
        js_click(page, "button.btnWidth", "立即支付 btnWidth")
    time.sleep(3)
    take_screenshot(page, "04d_after_payamount")

    # 第5步：弹窗 → 立即支付
    if not js_click(page, "button.pay-now", "弹窗立即支付"):
        try:
            page.evaluate("payNow();")
            log.info("直接调用 payNow()")
        except Exception as e:
            log.warning(f"payNow() 失败: {e}")
    time.sleep(3)
    take_screenshot(page, "04e_after_paynow")

    body = get_text(page)
    if "success" in body.lower() or "成功" in body or "/service" in page.url:
        log.info("✅ 续费完成")
        take_screenshot(page, "04f_renew_complete")
        return True, expiry_str, remain
    else:
        log.warning("续费流程可能未完成，请查看截图")
        return False, expiry_str, remain

# ---------- 主流程 ----------
def main():
    from cloakbrowser import launch

    log.info("启动 CloakBrowser（源码级指纹伪装）...")
    # geoip=True：根据代理 IP 自动匹配时区/语言，消除指纹矛盾
    browser = launch(
        headless=False,
        humanize=True,
        proxy=PROXY_SERVER,
        geoip=True,
    )
    # headed 模式下 no_viewport=True 是 CloakBrowser 0.4.0+ 的默认行为（无需显式传）；
    # 真正修复"Viewport size not available"崩溃的是 0.4.1 版本里 page.evaluate
    # 兜底读取 window.innerWidth/innerHeight，所以 requirements.txt 必须 >=0.4.1
    page = browser.new_page()

    try:
        if not login(page):
            wxpush("❌ 登录失败，请检查账号密码或网络")
            return

        balance = sign(page)
        renewed, expiry_str, remain = renew(page)

        # 续费后重新读最新到期日
        if renewed:
            try:
                page.goto(SERVICE_PAGE, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                new_expiry = read_expiry_from_service_page(page)
                if new_expiry:
                    expiry_str = new_expiry
                    log.info(f"续费后最新到期日: {expiry_str}")
            except Exception as e:
                log.warning(f"续费后读取到期日失败: {e}")

        # 积分为 None 时再读一次
        if balance is None:
            try:
                page.goto(SIGN_PAGE, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                body = get_text(page)
                bal = re.search(r'账户余额剩余\s*([\d.]+)\s*积分', body)
                if bal:
                    balance = bal.group(1)
            except Exception as e:
                log.warning(f"读取积分失败: {e}")

        lines = ["✅ 签到成功"]
        if balance is not None:
            lines.append(f"账户余额剩余 {balance} 积分")
        if expiry_str:
            lines.append(f"到期时间 {expiry_str}")
            if renewed:
                lines.append("✅ 已自动续期")
            else:
                renew_date = (
                    datetime.strptime(expiry_str, "%Y-%m-%d") - timedelta(days=2)
                ).strftime("%Y-%m-%d")
                lines.append(f"不用续期，等到 {renew_date} 再续期")
        wxpush("\n".join(lines))

    except Exception as e:
        log.exception(e)
        take_screenshot(page, "99_error")
        wxpush(f"❌ Runfreecloud 任务异常: {e}")
    finally:
        time.sleep(5)
        browser.close()
        log.info("任务结束")

if __name__ == "__main__":
    main()
