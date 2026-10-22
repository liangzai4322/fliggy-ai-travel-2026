#!/usr/bin/env python3
"""Repeatable FlyAI queries and an auditable budget. Python standard library only."""
import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import html
import json
from pathlib import Path
import re
import shutil
import subprocess


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def money(value):
    """Never treat ranges, unknown prices or non-CNY currencies as a quote."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not re.fullmatch(r"(?:[¥￥]|CNY\s*)?\d+(?:\.\d+)?(?:元)?", text):
        return None
    try:
        result = Decimal(re.sub(r"[¥￥元]|CNY\s*", "", text))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def validate(request):
    departure = date.fromisoformat(request["departure"])
    back = date.fromisoformat(request["return"])
    nights = (back - departure).days
    if not 1 <= nights <= 60:
        raise ValueError("返程必须晚于出发日期，且行程不超过60晚")
    for name in ("adults", "rooms"):
        if isinstance(request[name], bool) or not isinstance(request[name], int) or not 1 <= request[name] <= 20:
            raise ValueError(name + "必须为1至20的整数")
    for name in ("origin", "destination"):
        if not isinstance(request[name], str) or not request[name].strip() or request[name].startswith("-"):
            raise ValueError(name + "无效")
    for name in ("budget", "hotelMaxNight"):
        if money(request[name]) is None or money(request[name]) <= 0:
            raise ValueError(name + "必须为正金额")
    for value in request.get("estimates", {}).values():
        if money(value) is None:
            raise ValueError("估算费用必须为非负金额")
    return nights


def commands(request):
    hotel = ["flyai", "search-hotel", "--dest-name", request["destination"], "--check-in-date", request["departure"], "--check-out-date", request["return"]]
    if request.get("hotelStars"):
        hotel.extend(["--hotel-stars", str(request["hotelStars"])])
    hotel.extend(["--sort", request.get("hotelSort", "rate_desc"), "--max-price", str(request["hotelMaxNight"])])
    return {
        "outbound": ["flyai", "search-flight", "--origin", request["origin"], "--destination", request["destination"], "--dep-date", request["departure"], "--journey-type", "1", "--sort-type", "3"],
        "return": ["flyai", "search-flight", "--origin", request["destination"], "--destination", request["origin"], "--dep-date", request["return"], "--journey-type", "1", "--sort-type", "3"],
        "hotel": hotel
    }


def query(argv):
    started = datetime.now(timezone.utc).isoformat()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)
        try:
            raw = json.loads(p.stdout) if p.stdout.strip() else None
        except json.JSONDecodeError:
            raw = None
        # Do not persist arbitrary stderr: SDK errors could contain a header or token.
        error = None if p.returncode == 0 and raw is not None else "CLI查询失败，请在本机检查网络、额度和官方CLI配置；原始stderr未保存。"
        return {"time": started, "argv": argv, "exitCode": p.returncode, "response": raw, "error": error}
    except subprocess.TimeoutExpired:
        return {"time": started, "argv": argv, "exitCode": -1, "response": None, "error": "查询超过90秒，未自动重试"}


def candidates(record, kind):
    raw = record.get("response") or {}
    data = raw.get("data") or {}
    items = data.get("itemList") if isinstance(data, dict) else None
    # Do not parse products from a business-error response, even if data is present.
    if raw.get("status") not in (None, 0, "0") or record.get("exitCode") != 0:
        return []
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if kind == "hotel":
            result.append({"name": item.get("name", "酒店"), "price": item.get("price"), "url": item.get("detailUrl"), "image": item.get("mainPic"), "note": item.get("address", ""), "unit": "列表起价；每晚口径按官方文档推算，指定房型/人数/三晚成交价待核验"})
        else:
            journeys = item.get("journeys") or []
            segments = journeys[0].get("segments", []) if journeys else []
            segment = segments[0] if segments else {}
            field = "adultPrice" if item.get("adultPrice") is not None else "ticketPrice"
            unit = "成人列表票价；税费、行李及实际人数库存待核验" if field == "adultPrice" else "ticketPrice 原值；按人民币单人票价估算，税费、人数口径与库存待核验"
            result.append({"name": segment.get("marketingTransportNo", "航班"), "price": item.get(field), "priceField": field, "url": item.get("jumpUrl"), "image": item.get("picUrl"), "note": f'{segment.get("depStationShortName", "")} {segment.get("depDateTime", "")} → {segment.get("arrStationShortName", "")} {segment.get("arrDateTime", "")}', "unit": unit})
    return result


def build_report(request, records):
    nights = validate(request)
    groups = {}
    quotes = []
    unknown = ["航班税费与行李", "两人同价库存", "酒店指定房型、入住人数、税费及三晚成交价"]
    for key, label in (("outbound", "去程"), ("return", "返程"), ("hotel", "住宿")):
        record = records.get(key) or {}
        matches_request = record.get("argv") == commands(request)[key]
        options = candidates(record, key) if matches_request else []
        priced = [x for x in options if money(x["price"]) is not None]
        # Keep evidence ordering; choose the lowest parseable list price.
        preference = request.get("selection", {}).get(key)
        selected = next((x for x in priced if x["name"] == preference), None) if preference else (min(priced, key=lambda x: money(x["price"])) if priced else None)
        quantity = request["adults"] if key != "hotel" else nights * request["rooms"]
        amount = money(selected["price"]) * quantity if selected else None
        display = ([selected] + [x for x in options if x is not selected][:2]) if selected else options[:3]
        groups[key] = {"status": "returned" if options else "unavailable", "time": record.get("time"), "options": display, "selected": selected, "platformHint": (record.get("response") or {}).get("systemMessage"), "error": record.get("error") if matches_request else "证据查询条件与当前需求不符"}
        quotes.append({"label": label, "unitPrice": str(money(selected["price"])) if selected else None, "quantity": quantity, "amount": str(amount) if amount is not None else None, "status": "列表价推算" if selected else "待核验"})
        if selected and selected.get("priceField") == "ticketPrice":
            unknown.append(label + " ticketPrice 的单人及人民币口径")
        if selected is None:
            unknown.append(label + "价格")
    subtotal = sum((Decimal(x["amount"]) for x in quotes if x["amount"] is not None), Decimal(0))
    estimates = request.get("estimates", {})
    estimate_total = sum((money(x) for x in estimates.values()), Decimal(0))
    complete = all(x["amount"] is not None for x in quotes)
    reference = subtotal + estimate_total
    return {"title": "行程有数", "request": request, "nights": nights, "groups": groups, "ledger": quotes,
            "knownListSubtotal": str(subtotal), "estimateTotal": str(estimate_total),
            "referenceTotal": str(reference) if complete else None,
            "budget": str(money(request["budget"])), "unknown": unknown,
            "conclusion": "列表价加估算已超过预算，需要调整" if reference > money(request["budget"]) else "预算尚待核验；列表价和估算不构成成交保证",
            "source": "飞猪官方FlyAI CLI，原始响应见同目录JSON"}


def safe_url(value):
    return value if isinstance(value, str) and value.startswith("https://") else ""


def render(report):
    esc = lambda value: html.escape(str(value))
    request = report["request"]
    tiles = []
    for kind, label in (("outbound", "去程航班"), ("return", "返程航班"), ("hotel", "入住酒店")):
        group = report["groups"][kind]
        options = group["options"]
        body = ""
        for index, option in enumerate(options):
            image = safe_url(option.get("image"))
            url = safe_url(option.get("url"))
            body += ('<img alt="产品图片" src="' + esc(image) + '">' if image else '')
            badge = '<small class="choice">本次选择</small> ' if index == 0 and group.get("selected") else ''
            body += f'<div class="option">{badge}<strong>{esc(option["name"])}</strong><b>{esc(option["price"])}</b><p>{esc(option["note"])}</p><small>{esc(option["unit"])}</small>'
            if url:
                body += f'<p><a target="_blank" rel="noreferrer noopener" href="{esc(url)}">在飞猪核验价格 ↗</a></p>'
            body += '</div>'
        if not options:
            body = '<p class="missing">暂无有效数据。配置服务端凭据后重新运行查询。</p>'
        if group.get("platformHint"):
            body += f'<p class="hint">{esc(group["platformHint"])}</p>'
        tiles.append(f'<section><span class="eyebrow">{esc(label)}</span>{body}<small>查询时间 {esc(group["time"] or "未记录")}</small></section>')
    ledger = ''.join(f'<li><span>{esc(x["label"])} <small>× {x["quantity"]} · {esc(x["status"])}</small></span><b>{"¥" + esc(x["amount"]) if x["amount"] is not None else "待核验"}</b></li>' for x in report["ledger"])
    report_url = safe_url(request.get("aiReportUrl"))
    ai_link = f'<p><a href="{esc(report_url)}" target="_blank" rel="noreferrer noopener">查看百炼生成并经规则复核的完整四日行程 ↗</a></p>' if report_url else ''
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>行程有数 · 预算旅行助手</title>
<style>:root{--ink:#153b4e;--sea:#007e91;--pale:#edf6fa;--line:#d6e6ed;--sun:#ffce54}*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:16px/1.65 system-ui,"PingFang SC",sans-serif}header{background:var(--pale);padding:32px 6vw 56px;border-bottom:1px solid var(--line)}nav{display:flex;justify-content:space-between;align-items:center}nav b{font-size:22px;letter-spacing:.1em}.tag{font-size:12px;border:1px solid var(--sea);padding:5px 12px;border-radius:30px;color:var(--sea)}h1{font-family:"Songti SC","Noto Serif CJK SC",serif;font-size:clamp(34px,5vw,64px);line-height:1.3;font-weight:600;margin:40px 0 20px}p{margin:12px 0}.intro{max-width:620px}.eyebrow{display:block;color:var(--sea);font-size:13px;letter-spacing:.12em;margin-bottom:18px}main{max-width:1450px;margin:auto;padding:40px 6vw;display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:32px}.results{display:grid;gap:20px}section{border:1px solid var(--line);border-radius:15px;padding:26px}.option{padding:14px 0;border-bottom:1px solid var(--line)}.option:last-of-type{border-bottom:0}.option strong{font-size:20px}.option b{float:right;font:23px ui-monospace,monospace;color:var(--sea)}small{font-size:12px;color:#55737f}a{color:var(--sea);text-underline-offset:4px}aside{align-self:start;position:sticky;top:24px;padding:28px;background:var(--pale);border-radius:15px;border-top:8px solid var(--sun)}aside h2{margin-top:0}ul{padding:0;list-style:none}li{display:flex;justify-content:space-between;gap:20px;padding:14px 0;border-bottom:1px dashed #b2cbd7}li small{display:block}.total{font:32px ui-monospace,monospace}.missing{color:#866119}.note{background:#fff5da;padding:16px;border-radius:9px;font-size:13px}img{max-width:100%;max-height:180px;object-fit:cover;border-radius:8px}.hint{font-size:12px;color:#55737f}footer{padding:20px 6vw;color:#55737f;font-size:12px}a:focus-visible{outline:3px solid var(--sun);outline-offset:5px}@media(max-width:900px){main{grid-template-columns:1fr}aside{position:static}nav{gap:18px}.tag{font-size:10px}section{padding:20px}}@media print{aside{position:static}a{color:inherit}main{padding:20px}header{padding:20px}h1{margin:20px 0;font-size:34px}}</style>
<header><nav><b>行程有数</b><span class="tag">百炼 × 飞猪 · 真实数据查询</span></nav><h1>每一段行程，<br>每一笔花费，都有数。</h1><p class="intro">''' + esc(f'{request["origin"]} → {request["destination"]} · {request["departure"]} 至 {request["return"]} · {request["adults"]}名成人 · {report["nights"]}晚{request["rooms"]}间') + '''</p><small>这是一次查询的可复核快照。价格与余量会变化，预订前请在飞猪确认。</small>''' + ai_link + '''</header><main><div class="results">''' + ''.join(tiles) + '''<section><span class="eyebrow">轻松行程建议</span><p>抵达当天办理入住、周边散步；完整游玩日每天只安排一个主要片区，为用餐和休息留白；返程日按实际航班时间提前到机场。</p><small>此段为规划建议，未查询景区开放时间、天气或交通实时状态。</small></section></div><aside><span class="eyebrow">旅行预算单 · CNY</span><h2>总预算 ¥''' + esc(report["budget"]) + '''</h2><ul>''' + ledger + '''<li><span>餐饮 / 交通 / 活动 / 机动金<small>示例估算，可修改需求JSON</small></span><b>¥''' + esc(report["estimateTotal"]) + '''</b></li></ul><small>列表价 + 估算参考合计</small><p class="total">''' + ('¥' + esc(report["referenceTotal"]) if report["referenceTotal"] is not None else '待补齐') + '''</p><p class="note">''' + esc(report["conclusion"]) + '''</p><small>待核验：''' + esc('；'.join(report["unknown"])) + '''</small></aside></main><footer>行程有数 · 百炼负责理解需求和规划，飞猪提供产品查询。此报告不创建订单。</footer></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', default='examples/sanya.json')
    parser.add_argument('--output', default='output')
    parser.add_argument('--replay', help='读取此前本脚本生成的证据目录，不请求网络')
    args = parser.parse_args()
    request = read_json(args.request)
    validate(request)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = {}
    if not args.replay and not shutil.which('flyai'):
        parser.error('缺少官方CLI，请先安装 npm i -g @fly-ai/flyai-cli')
    if not args.replay and date.fromisoformat(request['departure']) < date.today():
        parser.error('出发日期已过去，请修改需求文件；历史证据可使用 --replay')
    for key, argv in commands(request).items():
        records[key] = read_json(Path(args.replay) / (key + '.json')) if args.replay else query(argv)
        save_json(output / (key + '.json'), records[key])
    report = build_report(request, records)
    save_json(output / 'report.json', report)
    (output / 'report.html').write_text(render(report), encoding='utf-8')
    print('报告已生成：' + str(output / 'report.html'))
    print(report['conclusion'])


if __name__ == '__main__':
    main()
