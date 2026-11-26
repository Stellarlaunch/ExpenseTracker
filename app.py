import os
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

database_url = os.getenv("DATABASE_URL", "sqlite:///expenses.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

CATEGORIES = ["Food", "Transport", "Rent", "Shopping", "Bills", "Entertainment", "Health", "Other"]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    expenses = db.relationship(
        "Expense", backref="user", lazy=True, cascade="all, delete-orphan"
    )


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.Date, nullable=False, default=date.today)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def parse_expense_form(form):
    """Validate form data. Returns (amount, category, description, date) or None."""
    try:
        amount = Decimal(form["amount"])
        if amount <= 0:
            return None
        expense_date = datetime.strptime(form["date"], "%Y-%m-%d").date()
    except (InvalidOperation, ValueError, KeyError):
        return None
    category = form.get("category", "")
    if category not in CATEGORIES:
        return None
    return amount, category, form.get("description", "").strip(), expense_date


def get_own_expense_or_404(expense_id):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first()
    if expense is None:
        abort(404)
    return expense


def last_n_months(n):
    """Return a list of (year, month) for the last n months, oldest first."""
    today = date.today()
    year, month = today.year, today.month
    months = []
    for _ in range(n):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if not username or len(password) < 6:
            flash("Username required and password must be at least 6 characters.")
            return redirect(url_for("register"))
        if User.query.filter_by(username=username).first():
            flash("Username already taken.")
            return redirect(url_for("register"))
        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash("Account created! Please log in.")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    expenses = (
        Expense.query.filter_by(user_id=current_user.id)
        .order_by(Expense.date.desc(), Expense.id.desc())
        .all()
    )

    # Monthly totals for the last 6 months
    months = last_n_months(6)
    monthly_totals = defaultdict(float)
    for e in expenses:
        monthly_totals[(e.date.year, e.date.month)] += float(e.amount)
    month_labels = [date(y, m, 1).strftime("%b %Y") for y, m in months]
    month_values = [round(monthly_totals[(y, m)], 2) for y, m in months]

    # Category breakdown for the current month
    today = date.today()
    category_totals = defaultdict(float)
    for e in expenses:
        if e.date.year == today.year and e.date.month == today.month:
            category_totals[e.category] += float(e.amount)
    category_labels = list(category_totals.keys())
    category_values = [round(v, 2) for v in category_totals.values()]
    this_month_total = round(sum(category_values), 2)

    return render_template(
        "dashboard.html",
        expenses=expenses,
        categories=CATEGORIES,
        today=today.isoformat(),
        month_labels=month_labels,
        month_values=month_values,
        category_labels=category_labels,
        category_values=category_values,
        this_month_total=this_month_total,
        this_month_name=today.strftime("%B %Y"),
    )


@app.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    parsed = parse_expense_form(request.form)
    if parsed is None:
        flash("Enter a valid positive amount, category and date.")
        return redirect(url_for("dashboard"))
    amount, category, description, expense_date = parsed
    expense = Expense(
        amount=amount,
        category=category,
        description=description,
        date=expense_date,
        user_id=current_user.id,
    )
    db.session.add(expense)
    db.session.commit()
    flash("Expense added.")
    return redirect(url_for("dashboard"))


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = get_own_expense_or_404(expense_id)
    if request.method == "POST":
        parsed = parse_expense_form(request.form)
        if parsed is None:
            flash("Enter a valid positive amount, category and date.")
            return redirect(url_for("edit_expense", expense_id=expense.id))
        expense.amount, expense.category, expense.description, expense.date = parsed
        db.session.commit()
        flash("Expense updated.")
        return redirect(url_for("dashboard"))
    return render_template("edit_expense.html", expense=expense, categories=CATEGORIES)


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = get_own_expense_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    flash("Expense deleted.")
    return redirect(url_for("dashboard"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)