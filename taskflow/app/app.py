import os
import time
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from models import db, User, Task
from forms import RegisterForm, LoginForm, TaskForm

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-this")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@db:5432/taskflow"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

REQUEST_COUNT = Counter(
    "taskflow_requests_total",
    "Total request count",
    ["method", "endpoint", "http_status"]
)

REQUEST_LATENCY = Histogram(
    "taskflow_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"]
)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def before_request():
    request.start_time = time.time()


@app.after_request
def after_request(response):
    duration = time.time() - getattr(request, "start_time", time.time())
    REQUEST_COUNT.labels(request.method, request.path, response.status_code).inc()
    REQUEST_LATENCY.labels(request.path).observe(duration)
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = RegisterForm()
    if form.validate_on_submit():
        existing_user = User.query.filter(
            (User.email == form.email.data) | (User.username == form.username.data)
        ).first()
        if existing_user:
            flash("Username or email already exists.", "danger")
            return redirect(url_for("register"))

        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    form = TaskForm()
    if form.validate_on_submit():
        task = Task(
            title=form.title.data,
            description=form.description.data,
            status=form.status.data,
            owner=current_user
        )
        db.session.add(task)
        db.session.commit()
        flash("Task created successfully.", "success")
        return redirect(url_for("dashboard"))

    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.id.desc()).all()
    return render_template("dashboard.html", form=form, tasks=tasks)


@app.route("/task/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    form = TaskForm(obj=task)

    if form.validate_on_submit():
        task.title = form.title.data
        task.description = form.description.data
        task.status = form.status.data
        db.session.commit()
        flash("Task updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_task.html", form=form, task=task)


@app.route("/task/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    task = Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "warning")
    return redirect(url_for("dashboard"))


@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Database tables created.")


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)