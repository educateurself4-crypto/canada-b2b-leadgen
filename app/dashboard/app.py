"""Internal dashboard: search/filter/export businesses, view pipeline health,
and set the Do-Not-Call flag. Deliberately plain (server-rendered Flask +
minimal JS) so it runs anywhere with zero build step — easy to hand off
and easy to later swap the front end for something fancier once this is
wired into a CRM/dialer.
"""
import threading
from functools import wraps
# pyrefly: ignore [missing-import]
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

app = Flask(__name__)
app.secret_key = config.DASHBOARD_SECRET_KEY


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
        "incorporation_date": "incorporation_date"
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
        where_clauses.append("province ILIKE %s"); params.append(f"%{filters['province']}%")
    if filters["city"]:
        where_clauses.append("city ILIKE %s"); params.append(f"%{filters['city']}%")
    if filters["industry"]:
        where_clauses.append("industry ILIKE %s"); params.append(f"%{filters['industry']}%")
    if filters["size_category"]:
        where_clauses.append("size_category = %s"); params.append(filters["size_category"])
    if filters["min_quality_score"]:
        where_clauses.append("quality_score >= %s"); params.append(filters["min_quality_score"])
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
        sort_by=sort_by, sort_order=sort_order, build_sort_url=build_sort_url
    )


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

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get("X-API-Key") != config.AUTOMATION_API_KEY:
            abort(401, description="Unauthorized")
        return f(*args, **kwargs)
    return decorated_function

@app.route("/api/leads/new", methods=["GET"])
@require_api_key
def api_leads_new():
    window = request.args.get("window", "today")
    min_score = request.args.get("min_quality_score", 0, type=int)
    
    event_type = 'new_today'
    if window == '7d': event_type = 'new_7d'
    if window == '30d': event_type = 'new_30d'

    with get_cursor() as (cur, conn):
        cur.execute(
            """SELECT b.id, b.legal_name, b.operating_name, b.city, b.province, 
                      b.industry, b.quality_score, b.phone 
               FROM businesses b
               JOIN new_business_events e ON e.business_id = b.id
               WHERE e.event_type = %s AND b.quality_score >= %s
               ORDER BY b.quality_score DESC""",
            (event_type, min_score)
        )
        leads = cur.fetchall()
        
    return jsonify({"count": len(leads), "leads": [dict(l) for l in leads]})

@app.route("/api/jobs/recent", methods=["GET"])
@require_api_key
def api_jobs_recent():
    status = request.args.get("status")
    since = request.args.get("since")
    
    where = []
    params = []
    if status:
        where.append("status = %s")
        params.append(status)
    if since:
        where.append("started_at >= %s")
        params.append(since)
        
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    
    with get_cursor() as (cur, conn):
        cur.execute(
            f"""SELECT source_name, job_type, errors_count, started_at, error_detail 
               FROM job_runs {where_sql} ORDER BY started_at DESC LIMIT 50""",
            params
        )
        jobs = cur.fetchall()
        
    result = []
    for j in jobs:
        d = dict(j)
        if d['started_at']: d['started_at'] = d['started_at'].isoformat()
        result.append(d)
        
    return jsonify(result)

@app.route("/api/trigger/<source_name>", methods=["POST"])
@require_api_key
def api_trigger(source_name):
    if source_name == 'corporations_canada_federal':
        connector = FederalCorporationsCanadaConnector()
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT)
