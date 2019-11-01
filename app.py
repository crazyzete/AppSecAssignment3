from flask import Flask, request, redirect, render_template, make_response, Response
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired
from flask_wtf.csrf import CSRFProtect
import secrets
import subprocess
import os
import datetime
from passlib.hash import sha256_crypt
from flask_sqlalchemy import SQLAlchemy


app = Flask(__name__)



login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

app.secret_key = secrets.token_urlsafe(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///theDB.db'

csrf = CSRFProtect(app)


db = SQLAlchemy()

class User(UserMixin, db.Model):
    """Model for user accounts."""

    __tablename__ = 'users'

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    uname = db.Column(db.String(25), nullable=False, unique=True)

    pword = db.Column(db.String(80), nullable=False)

    twofa = db.Column(db.String(25))

    isAdmin = db.Column(db.Boolean, nullable=False)

    def __init__(self, uname, pword, twofa):
        self.uname = uname
        self.pword = pword
        self.twofa = twofa

    def getPassword(self):
        return self.pword

    def get2FA(self):
        return self.twofa

    def getUname(self):
        return self.uname

    def get_id(self):
        return self.getUname()

    # I'm not including a seperate SALT, the project requirements do not specify it. I am using passlib which generates
    # a hash including the salt and automatically handles that part.

    def __repr__(self):
        return '<User {}>'.format(self.username)

class LoginRecord(db.Model):
    __tablename__ = 'login_records'
    record_number =  db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    log_on = db.Column(db.DateTime, nullable=False)
    log_off = db.Column(db.DateTime, nullable=True)
    user = db.relationship(User)

class QueryRecord(db.Model):
    __tablename__ = 'query_records'
    record_number =  db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    query_text = db.Column(db.Text, nullable=True)
    query_result  = db.Column(db.Text, nullable=True)
    time = db.Column(db.DateTime, nullable=False)
    user = db.relationship(User)


@login_manager.user_loader
def load_user(id):
    existing_user = User.query.filter_by(uname=id).first()
    return existing_user

with app.app_context():
    db.init_app(app)
    db.create_all()
    if not load_user('admin'):
         adminUser = User('admin', sha256_crypt.hash('Administrator@1'), '12345678901')
         adminUser.isAdmin = True
         db.session.add(adminUser)
         db.session.commit()

class UserForm(FlaskForm):
    uname = StringField('User Name:', validators=[DataRequired()])
    pword = StringField('Password: ', validators=[DataRequired()])
    twofa = StringField('2FA Token:', validators=[], id='2fa')


def addUser(uname, pword, twofa):
    user = User(uname, sha256_crypt.hash(pword), twofa)
    user.isAdmin = False
    db.session.add(user)
    db.session.commit()

def passwordMatch(user, pword):
    if sha256_crypt.verify(pword, user.getPassword()):
        return True
    else:
        return False


def twofaMatch(user, twofa):
    if user.get2FA() == twofa:
        return True
    else:
        return False


def addLogonRecord(uname):
    record = LoginRecord()
    record.user_id = uname
    record.log_on = datetime.datetime.utcnow()
    db.session.add(record)
    db.session.commit()

def updateLogonRecordAtLogoff(uname):
   earliestLogin = LoginRecord.query.filter_by(user_id=uname, log_off=None).order_by(LoginRecord.log_on).first()
   earliestLogin.log_off = datetime.datetime.utcnow()
   db.session.add(earliestLogin)
   db.session.commit()

def addQueryRecord(querytext, queryresult):
    query = QueryRecord()
    query.user_id = current_user.getUname()
    query.query_text = querytext
    query.query_result = queryresult
    query.time = datetime.datetime.utcnow()
    db.session.add(query)
    db.session.commit()

def secureResponse(render):
    response = make_response(render)
    response.headers['X-XSS-Protection'] = '1; mode=block'
    #response.headers['Content-Security-Policy'] = "default-src '127.0.0.1:5000'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return response

@app.errorhandler(404)
def not_found(e):
    return secureResponse(render_template("PageNotFound.html"))

@app.route('/register', methods=('GET', 'POST'))
def register():
    form = UserForm()
    if form.validate_on_submit():
        # return redirect('/success')

        user = form.uname.data
        pword = form.pword.data
        twofa = form.twofa.data

        if (load_user(user)) or (not user) or (not pword):
            return secureResponse(render_template('registrationResult.html', success="Failure"))
        else:
            addUser(user, pword, twofa)
            return secureResponse(render_template('registrationResult.html', success="Success"))

    return secureResponse(render_template('registerForm.html', form=form))


@app.route('/login', methods=('GET', 'POST'))
def login():
    form = UserForm()
    if form.validate_on_submit():
        # return redirect('/success')

        global userDict

        user = form.uname.data
        pword = form.pword.data
        twofa = form.twofa.data

        theUser = load_user(user)
        if theUser:
            if passwordMatch(theUser, pword):
                if twofaMatch(theUser, twofa):
                    login_user(theUser, remember=True)
                    addLogonRecord(theUser.uname)
                    return secureResponse(render_template('loginResult.html', result="Success"))
                else:
                    return secureResponse(render_template('loginResult.html', result="Two-factor Failure"))
            else:
                return secureResponse(render_template('loginResult.html', result="Incorrect"))
        else:
            return secureResponse(render_template('loginResult.html', result="Incorrect"))

    return secureResponse(render_template('userLoginForm.html', form=form))

@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        updateLogonRecordAtLogoff(current_user.getUname())
        logout_user()
    return redirect('/login')

class AdminHistoryForm(FlaskForm):
    userquery = StringField('Username to Query:', validators=[DataRequired()])

@app.route('/history/query<int:query_number>')
@login_required
def queryReview(query_number):
    record = QueryRecord.query.filter_by(record_number=query_number).first()

    if record is None:
        return secureResponse(render_template('QueryNotFound.html'))
    elif current_user.isAdmin or (record.user_id == current_user.getUname()):
        return secureResponse(render_template('queryReview.html', query_number=record.record_number, uname=record.user_id,
                                              text=record.query_text, results=record.query_result))
    else:
        return secureResponse(render_template('QueryNotAuthorized.html'))

@app.route('/history', methods=('GET', 'POST'))
@login_required
def history():

    form = AdminHistoryForm()

    uname = current_user.getUname()

    if current_user.isAdmin and form.validate_on_submit():
        uname = form.userquery.data
    elif current_user.isAdmin:
        return  secureResponse(render_template('historyAdminForm.html', form=form))

    results = QueryRecord.query.filter_by(user_id=uname).order_by(QueryRecord.record_number)

    return secureResponse(render_template('recordResults.html', records=results))

@app.route('/login_history', methods=('GET', 'POST'))
@login_required
def login_history():

    form = AdminHistoryForm()

    uname = current_user.getUname()

    if current_user.isAdmin and form.validate_on_submit():
        results = LoginRecord.query.filter_by(user_id=form.userquery.data).order_by(LoginRecord.record_number)
        return secureResponse(render_template('loginHistory.html', records=results))
    elif current_user.isAdmin:
        return  secureResponse(render_template('loginHistoryForm.html', form=form))
    else:
        return secureResponse(render_template('QueryNotAuthorized.html'))


class spellCheckForm(FlaskForm):
    inputtext = TextAreaField(u'Text to Check', [DataRequired()], render_kw={"rows": 40, "cols": 100})


@app.route('/spell_check', methods=('GET', 'POST'))
@login_required
def spellcheck():
    form = spellCheckForm()

    if form.validate_on_submit():
        # return redirect('/success')

        text = form.inputtext.data

        f = open("tempUserInput", "w")
        f.write(text)
        f.close()

        process = subprocess.run(['./a.out', 'tempUserInput', 'wordlist.txt'], check=True, stdout=subprocess.PIPE,
                                 universal_newlines=True)
        output = process.stdout

        os.remove("tempUserInput")

        misspelledOut = output.replace("\n", ", ").strip().strip(',')

        addQueryRecord(text, misspelledOut)

        return secureResponse(render_template('spellCheckResult.html', misspelled=misspelledOut, textout=text))

    else:
        return secureResponse(render_template('spellCheckForm.html', form=form))



if __name__ == '__main__':
    app.run(debug=True)
