"""Internal dashboard: search/filter/export businesses, view pipeline health,
business detail view, and Do-Not-Call management. Dark-themed, responsive Flask
dashboard with API endpoints for CRM/dialer integration.
"""
import threading
from functools import wraps
from flask import Flask, render_template, request, Response, redirect, url_for, jsonify, abort
from app.db import get_cursor
from app.export.csv_export import export_businesses_csv
from app.pipeline.new_business_detector import rolling_window_counts
from app.config import config
from app.pipeline.orchestrator import run_connector
from app.connectors.federal_corporations_canada import FederalCorporationsCanadaConnector
from app.connectors.ckan_open_data import CkanOpenDataConnector, SOURCE_REGISTRY as CKAN_SOURCES
from app.connectors.socrata_open_data import SocrataOpenDataConnector, SOURCE_REGISTRY as SOCRATA_SOURCES
from app.connectors.opendatasoft import OpendatasoftConnector, SOURCE_REGISTRY as ODS_SOURCES
from app.connectors.bc_orgbook import BCOrgBookConnector

app = Flask(__name__)
app.secret_key = config.DASHBOARD_SECRET_KEY


# ── Main dashboard view ─────────────────────────────────────────────────

@app.route("/")
def index():
    filters = {
        "search": request.args.get("search") or None,
        "province": request.args.get("province") or None,
        "city": request.args.get("city") or None,
        "industry": request.args.get("industry") or None,
        "size_category": request.args.get("size_category") or None,
        "min_quality_score": request.args.get("min_quality_score") or None,
        "phone_available": request.args.get("phone_available") == "on",
        "email_available": request.args.get("email_available") == "on",
        "new_only": request.args.get("new_only") == "on",
        "decision_maker_available": request.args.get("decision_maker_available") == "on",
    }

    sort_by = request.args.get("sort_by", "quality_score")
    sort_order = request.args.get("sort_order", "desc").upper()

    valid_columns = {
        "legal_name": "legal_name",
        "operating_name": "operating_name",
        "province": "province",
        "city": "city",
        "phone": "phone",
        "email": "email",
        "industry": "industry",
        "size_category": "size_category",
        "business_status": "business_status",
        "quality_score": "quality_score",
        "first_seen_at": "first_seen_at",
        "incorporation_date": "incorporation_date",
    }

    if sort_by not in valid_columns:
        sort_by = "quality_score"
    if sort_order not in ["ASC", "DESC"]:
        sort_order = "DESC"

    order_sql = f"ORDER BY {valid_columns[sort_by]} {sort_order} NULLS LAST"

    where_clauses, params = ["do_not_call = FALSE"], []
    if filters["search"]:
        where_clauses.append("(legal_name ILIKE %s OR operating_name ILIKE %s)")
        params.extend([f"%{filters['search']}%", f"%{filters['search']}%"])
    if filters["province"]:
        where_clauses.append("province = %s")
        params.append(filters["province"])
    if filters["city"]:
        where_clauses.append("city ILIKE %s")
        params.append(f"%{filters['city']}%")
    if filters["industry"]:
        where_clauses.append("industry ILIKE %s")
        params.append(f"%{filters['industry']}%")
    if filters["size_category"]:
        where_clauses.append("size_category = %s")
        params.append(filters["size_category"])
    if filters["min_quality_score"]:
        where_clauses.append("quality_score >= %s")
        params.append(filters["min_quality_score"])
    if filters["phone_available"]:
        where_clauses.append("phone IS NOT NULL")
    if filters["email_available"]:
        where_clauses.append("email IS NOT NULL")
    if filters["new_only"]:
        where_clauses.append(
            "id IN (SELECT business_id FROM new_business_events WHERE event_type IN ('new_today','new_7d','new_30d'))"
        )
    if filters["decision_maker_available"]:
        where_clauses.append("id IN (SELECT business_id FROM contacts WHERE is_active)")

    where_sql = " AND ".join(where_clauses)

    with get_cursor() as (cur, conn):
        cur.execute(
            f"""SELECT id, legal_name, operating_name, province, city, phone, email,
                       industry, size_category, quality_score, lead_ready, business_status,
                       first_seen_at, incorporation_date
                FROM businesses WHERE {where_sql}
                {order_sql} LIMIT 200""",
            params,
        )
        businesses = cur.fetchall()

        cur.execute(f"SELECT count(*) AS n FROM businesses WHERE {where_sql}", params)
        total = cur.fetchone()["n"]

        cur.execute(
            """SELECT source_name, status, started_at, finished_at, records_collected,
                      records_new, records_updated, errors_count
               FROM job_runs ORDER BY started_at DESC LIMIT 10"""
        )
        recent_jobs = cur.fetchall()

        new_counts = rolling_window_counts(cur)

        cur.execute(
            """SELECT b.id, b.legal_name, b.operating_name, b.city, b.province,
                      b.industry, b.quality_score, b.phone
               FROM businesses b
               JOIN new_business_events e ON e.business_id = b.id
               WHERE e.event_type = 'new_today'
               ORDER BY b.quality_score DESC LIMIT 15"""
        )
        daily_digest = cur.fetchall()

    def build_sort_url(column):
        args = request.args.copy()
        args["sort_by"] = column
        if sort_by == column and sort_order == "ASC":
            args["sort_order"] = "DESC"
        else:
            args["sort_order"] = "ASC"
        return url_for("index", **args)

    return render_template(
        "index.html", businesses=businesses, total=total, filters=request.args,
        recent_jobs=recent_jobs, new_counts=new_counts, daily_digest=daily_digest,
        sort_by=sort_by, sort_order=sort_order, build_sort_url=build_sort_url,
        config=config,
    )


# ── Business Detail View ────────────────────────────────────────────────

@app.route("/business/<business_id>")
def business_detail(business_id):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT * FROM businesses WHERE id = %s", (business_id,))
        business = cur.fetchone()
        if not business:
            abort(404)

        cur.execute(
            """SELECT * FROM contacts WHERE business_id = %s AND is_active ORDER BY confidence DESC""",
            (business_id,),
        )
        contacts = cur.fetchall()

        cur.execute(
            """SELECT field_name, field_value, source_name, source_kind, confidence,
                      retrieved_at, is_current_pick
               FROM business_field_sources WHERE business_id = %s
               ORDER BY field_name, confidence DESC""",
            (business_id,),
        )
        field_sources = cur.fetchall()

        cur.execute(
            """SELECT event_type, detected_at, detail
               FROM new_business_events WHERE business_id = %s
               ORDER BY detected_at DESC LIMIT 20""",
            (business_id,),
        )
        events = cur.fetchall()

    return render_template(
        "detail.html", business=business, contacts=contacts,
        field_sources=field_sources, events=events,
    )


# ── CSV Export ──────────────────────────────────────────────────────────

@app.route("/export.csv")
def export_csv():
    filters = {
        "search": request.args.get("search") or None,
        "province": request.args.get("province") or None,
        "city": request.args.get("city") or None,
        "industry": request.args.get("industry") or None,
        "size_category": request.args.get("size_category") or None,
        "min_quality_score": request.args.get("min_quality_score") or None,
        "phone_available": request.args.get("phone_available") == "on",
        "email_available": request.args.get("email_available") == "on",
        "new_only": request.args.get("new_only") == "on",
        "decision_maker_available": request.args.get("decision_maker_available") == "on",
    }
    csv_text = export_businesses_csv(filters)
    return Response(
        csv_text, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )


# ── Do-Not-Call ─────────────────────────────────────────────────────────

@app.route("/business/<business_id>/do-not-call", methods=["POST"])
def mark_do_not_call(business_id):
    reason = request.form.get("reason", "Requested by business")
    with get_cursor() as (cur, conn):
        cur.execute(
            "UPDATE businesses SET do_not_call = TRUE, do_not_call_reason = %s, do_not_call_at = now() WHERE id = %s",
            (reason, business_id),
        )
        cur.execute(
            "INSERT INTO do_not_call_requests (business_id, requested_by, channel, note) VALUES (%s, %s, %s, %s)",
            (business_id, request.form.get("requested_by", "dashboard"), "manual", reason),
        )
    return redirect(url_for("index"))


# ── API Auth ────────────────────────────────────────────────────────────

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get("X-API-Key") != config.AUTOMATION_API_KEY:
            abort(401, description="Unauthorized")
        return f(*args, **kwargs)
    return decorated_function


# ── API: New Leads ──────────────────────────────────────────────────────

@app.route("/api/leads/new", methods=["GET"])
@require_api_key
def api_leads_new():
    window = request.args.get("window", "today")
    min_score = request.args.get("min_quality_score", 0, type=int)

    event_type = "new_today"
    if window == "7d":
        event_type = "new_7d"
    if window == "30d":
        event_type = "new_30d"

    with get_cursor() as (cur, conn):
        cur.execute(
            """SELECT b.id, b.legal_name, b.operating_name, b.city, b.province,
                      b.industry, b.quality_score, b.phone, b.email, b.website,
                      b.size_category, b.incorporation_date
               FROM businesses b
               JOIN new_business_events e ON e.business_id = b.id
               WHERE e.event_type = %s AND b.quality_score >= %s
                 AND b.do_not_call = FALSE
               ORDER BY b.quality_score DESC""",
            (event_type, min_score),
        )
        leads = cur.fetchall()

    return jsonify({"count": len(leads), "leads": [dict(l) for l in leads]})


# ── API: Stats Summary ─────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
@require_api_key
def api_stats():
    with get_cursor() as (cur, conn):
        cur.execute("SELECT count(*) AS total FROM businesses WHERE do_not_call = FALSE")
        total = cur.fetchone()["total"]

        cur.execute("SELECT count(*) AS total FROM businesses WHERE lead_ready AND do_not_call = FALSE")
        lead_ready = cur.fetchone()["total"]

        cur.execute(
            "SELECT province, count(*) AS cnt FROM businesses WHERE do_not_call = FALSE GROUP BY province ORDER BY cnt DESC"
        )
        by_province = {r["province"]: r["cnt"] for r in cur.fetchall() if r["province"]}

        cur.execute(
            "SELECT size_category, count(*) AS cnt FROM businesses WHERE size_category IS NOT NULL AND do_not_call = FALSE GROUP BY size_category ORDER BY cnt DESC"
        )
        by_size = {r["size_category"]: r["cnt"] for r in cur.fetchall()}

        new_counts = rolling_window_counts(cur)

    return jsonify({
        "total_businesses": total,
        "lead_ready": lead_ready,
        "by_province": by_province,
        "by_size": by_size,
        "new_counts": new_counts,
    })


# ── API: Recent Jobs ───────────────────────────────────────────────────

@app.route("/api/jobs/recent", methods=["GET"])
@require_api_key
def api_jobs_recent():
    status_filter = request.args.get("status")
    since = request.args.get("since")

    where = []
    params = []
    if status_filter:
        where.append("status = %s")
        params.append(status_filter)
    if since:
        where.append("started_at >= %s")
        params.append(since)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    with get_cursor() as (cur, conn):
        cur.execute(
            f"""SELECT source_name, job_type, status, records_collected,
                       records_new, records_updated, errors_count,
                       started_at, finished_at, error_detail
               FROM job_runs {where_sql} ORDER BY started_at DESC LIMIT 50""",
            params,
        )
        jobs = cur.fetchall()

    result = []
    for j in jobs:
        d = dict(j)
        if d["started_at"]:
            d["started_at"] = d["started_at"].isoformat()
        if d.get("finished_at"):
            d["finished_at"] = d["finished_at"].isoformat()
        result.append(d)

    return jsonify(result)


# ── API: Trigger Source ─────────────────────────────────────────────────

@app.route("/api/trigger/<source_name>", methods=["POST"])
@require_api_key
def api_trigger(source_name):
    if source_name == "corporations_canada_federal":
        connector = FederalCorporationsCanadaConnector()
    elif source_name == "bc_orgbook":
        connector = BCOrgBookConnector()
    else:
        # Search across all platform registries
        cfg = next((c for c in CKAN_SOURCES if c.key == source_name), None)
        if cfg:
            connector = CkanOpenDataConnector(cfg)
        else:
            cfg = next((c for c in SOCRATA_SOURCES if c.key == source_name), None)
            if cfg:
                connector = SocrataOpenDataConnector(cfg)
            else:
                cfg = next((c for c in ODS_SOURCES if c.key == source_name), None)
                if cfg:
                    connector = OpendatasoftConnector(cfg)
                else:
                    abort(404, description="Source not found")

    threading.Thread(target=run_connector, args=(connector,)).start()
    return jsonify({"status": "triggered", "source": source_name})


# ── API: Business Detail ───────────────────────────────────────────────

@app.route("/api/business/<business_id>", methods=["GET"])
@require_api_key
def api_business_detail(business_id):
    with get_cursor() as (cur, conn):
        cur.execute("SELECT * FROM businesses WHERE id = %s", (business_id,))
        business = cur.fetchone()
        if not business:
            abort(404)

        cur.execute(
            "SELECT * FROM contacts WHERE business_id = %s AND is_active",
            (business_id,),
        )
        contacts = cur.fetchall()

    result = dict(business)
    # Convert datetime fields to ISO
    for key in ["first_seen_at", "last_verified_at", "last_updated_at", "created_at", "do_not_call_at"]:
        if result.get(key):
            result[key] = result[key].isoformat()
    if result.get("incorporation_date"):
        result["incorporation_date"] = str(result["incorporation_date"])

    result["contacts"] = [dict(c) for c in contacts]
    for c in result["contacts"]:
        if c.get("retrieved_at"):
            c["retrieved_at"] = c["retrieved_at"].isoformat()

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT)
