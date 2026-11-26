import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")

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
    return render_template(
        "dashboard.html",
        expenses=expenses,
        categories=CATEGORIES,
        today=date.today().isoformat(),
    )


@app.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    try:
        amount = Decimal(request.form["amount"])
        if amount <= 0:
            raise InvalidOperation
        expense_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
    except (InvalidOperation, ValueError):
        flash("Enter a valid positive amount and date.")
        return redirect(url_for("dashboard"))

    category = request.form["category"]
    if category not in CATEGORIES:
        flash("Invalid category.")
        return redirect(url_for("dashboard"))

    expense = Expense(
        amount=amount,
        category=category,
        description=request.form.get("description", "").strip(),
        date=expense_date,
        user_id=current_user.id,
    )
    db.session.add(expense)
    db.session.commit()
    flash("Expense added.")
    return redirect(url_for("dashboard"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)