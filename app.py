# -*- coding: utf-8 -*-
import os, sqlite3, random
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, send_from_directory

APP_TITLE="СпецТех"; DB="data.sqlite"
app=Flask(__name__); app.config["SECRET_KEY"]="change_this"; 
for d in ("uploads","banners"): os.makedirs(d, exist_ok=True)

def db(): 
    if "db" not in g: 
        g.db=sqlite3.connect(DB, timeout=5); g.db.row_factory=sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(_): 
    d=g.pop("db",None); 
    d and d.close()

def setup():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, phone TEXT UNIQUE, name TEXT, whatsapp TEXT, is_admin INT DEFAULT 0, is_verified INT DEFAULT 0);
    CREATE TABLE IF NOT EXISTS brands(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS listings(
        id INTEGER PRIMARY KEY, title TEXT, description TEXT, brand_id INT, category_id INT, price REAL, image TEXT,
        user_id INT, seller_phone TEXT, whatsapp_enabled INT DEFAULT 1, call_enabled INT DEFAULT 1, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, val TEXT);
    """)
    c.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('whatsapp_global','1')")
    c.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('allow_calls','1')")
    for b in ("Shacman","Howo","Sinotruk","XCMG","Foton"): c.execute("INSERT OR IGNORE INTO brands(name) VALUES(?)",(b,))
    for cat in ("Шасси","Подъёмник","Сиденье","Двигатель","Тормоза"): c.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)",(cat,))
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]==0:
        c.execute("INSERT INTO users(phone,name,whatsapp,is_admin,is_verified) VALUES(?,?,?,?,1)",("+992900000000","Админ","+992900000000",1))
        c.execute("INSERT INTO users(phone,name,whatsapp,is_verified) VALUES(?,?,?,1)",("+992911111111","Продавец","+992911111111"))
    if c.execute("SELECT COUNT(*) FROM listings").fetchone()[0]==0:
        seller_id=c.execute("SELECT id FROM users WHERE phone='+992911111111'").fetchone()[0]
        b=lambda n: c.execute("SELECT id FROM brands WHERE name=?", (n,)).fetchone()[0]
        cat=lambda n: c.execute("SELECT id FROM categories WHERE name=?", (n,)).fetchone()[0]
        items=[("Фара Shacman F3000","Оригинал",b("Shacman"),cat("Шасси"),1450,"sample1.png"),
               ("Колодки Howo","Комплект",b("Howo"),cat("Тормоза"),380,"sample2.png"),
               ("Фильтр Sinotruk","Качество",b("Sinotruk"),cat("Двигатель"),120,"sample3.png")]
        for t,d,br,ct,pr,img in items:
            c.execute("""INSERT INTO listings(title,description,brand_id,category_id,price,image,user_id,seller_phone,whatsapp_enabled,call_enabled,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(t,d,br,ct,pr,img,seller_id,"+992911111111",1,1,datetime.now(timezone.utc).isoformat()))
    c.commit()

@app.before_request
def boot(): setup()

def cur_user():
    if "uid" in session: return db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()

@app.context_processor
def inject():
    s={r["key"]:r["val"] for r in db().execute("SELECT key,val FROM settings")}
    return dict(APP_TITLE=APP_TITLE, user=cur_user(), settings=s)

@app.route("/")
def index():
    q=request.args.get("q","").strip(); brand=request.args.get("brand",""); cat=request.args.get("category","")
    sql="""SELECT l.*, b.name brand_name, c.name cat_name FROM listings l 
           LEFT JOIN brands b ON b.id=l.brand_id LEFT JOIN categories c ON c.id=l.category_id WHERE 1=1"""
    args=[]; 
    if q: sql+=" AND (l.title LIKE ? OR l.description LIKE ?)"; like=f"%{q}%"; args+= [like,like]
    if brand: sql+=" AND l.brand_id=?"; args.append(brand)
    if cat: sql+=" AND l.category_id=?"; args.append(cat)
    sql+=" ORDER BY l.id DESC"
    rows=db().execute(sql,args).fetchall()
    brands=db().execute("SELECT * FROM brands").fetchall()
    cats=db().execute("SELECT * FROM categories").fetchall()
    return render_template("index.html", rows=rows, brands=brands, categories=cats, brand_id=brand, cat_id=cat, q=q)

@app.route("/listing/<int:lid>")
def listing(lid):
    r=db().execute("""SELECT l.*, b.name brand_name, c.name cat_name, u.whatsapp seller_whatsapp FROM listings l
                      LEFT JOIN brands b ON b.id=l.brand_id LEFT JOIN categories c ON c.id=l.category_id
                      LEFT JOIN users u ON u.id=l.user_id WHERE l.id=?""",(lid,)).fetchone()
    if not r: return "Not found",404
    s={x["key"]: x["val"] for x in db().execute("SELECT key,val FROM settings")}
    wa_on=(s.get("whatsapp_global","1")=="1" and r["whatsapp_enabled"]==1 and r["seller_whatsapp"])
    call_on=(s.get("allow_calls","1")=="1" and r["call_enabled"]==1 and r["seller_phone"])
    return render_template("listing_detail.html", row=r, wa_on=wa_on, call_on=call_on)

@app.route("/uploads/<path:f>")
def uploads(f): return send_from_directory("uploads", f)

# Admin (login fixed)
def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        if not session.get("admin"): return redirect(url_for("admin_login"))
        return f(*a,**k)
    return w

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        if request.form["login"]=="admin" and request.form["password"]=="admin123":
            session["admin"]=True; return redirect(url_for("admin"))
        flash("Неверные данные")
    return render_template("admin_login.html")

@app.route("/admin")
@admin_required
def admin():
    c=db()
    counts={
        "users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "listings": c.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    }
    s={r["key"]:r["val"] for r in c.execute("SELECT key,val FROM settings")}
    rows=c.execute("SELECT id,title,price FROM listings ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("admin_dashboard.html", counts=counts, settings=s, listings=rows)

@app.route("/admin/settings", methods=["POST"])
@admin_required
def admin_settings():
    c=db()
    c.execute("INSERT OR REPLACE INTO settings(key,val) VALUES('whatsapp_global',?)", ("1" if request.form.get("whatsapp_global")=="on" else "0",))
    c.execute("INSERT OR REPLACE INTO settings(key,val) VALUES('allow_calls',?)", ("1" if request.form.get("allow_calls")=="on" else "0",))
    c.commit(); return redirect(url_for("admin"))

@app.route("/admin/listing/delete/<int:lid>", methods=["POST"])
@admin_required
def admin_del(lid):
    db().execute("DELETE FROM listings WHERE id=?", (lid,)); db().commit(); return redirect(url_for("admin"))

if __name__=="__main__":
    app.run(host="127.0.0.1", port=5000)
