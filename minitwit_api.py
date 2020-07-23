from __future__ import with_statement
import time
from sqlite3 import dbapi2 as sqlite3
from hashlib import md5
from datetime import datetime
from contextlib import closing
from flask import Flask, request, session, url_for, redirect, \
     render_template, abort, g, flash
from werkzeug.security import check_password_hash, generate_password_hash
from flask_restful import Resource, Api, reqparse
from threading import Thread

# configuration
DATABASE = 'minitwit.db'
PER_PAGE = 30
DEBUG = True
SECRET_KEY = 'development key'

# 객체 생성
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('MINITWIT_SETTINGS', silent=True)

api = Api(app)

class Data(Resource):
    def get(self):

        parser = reqparse.RequestParser()
        
        messages = query_db('''
        select message.text, message.pub_date, user.username 
        from message, user
        where message.author_id = user.user_id
        order by message.pub_date desc limit ?''', [PER_PAGE])

        for message in messages:
            message['pub_date'] = format_datetime(message['pub_date'])
  
        parser.add_argument('messages', type=str)
        args = parser.parse_args()
        return {'messages':messages}

class DataOne(Resource):
    def get(self, name):
        parser = reqparse.RequestParser()
        messages = query_db('''
        select message.text, message.pub_date, user.username
        from message, user
        where message.author_id = user.user_id and
        user.username = ?
        order by message.pub_date desc limit ?''', 
        [name, PER_PAGE])

        for message in messages:
            message['pub_date'] = format_datetime(message['pub_date'])
        parser.add_argument('messages', type=str)
        args = parser.parse_args()
        return {'messages' : messages}
    
api.add_resource(Data, '/data')
api.add_resource(DataOne, '/<name>/data')

def connect_db():
    """DB연결"""
    return sqlite3.connect(app.config['DATABASE'])

def init_db():
    """DB초기화"""
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def query_db(query, args=(), one=False):
    """DB데이터를 쿼리화"""
    cur = g.db.execute(query, args)
    rv = [dict((cur.description[idx][0], value) for idx, value in enumerate(row)) \
          for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv

def get_user_id(username):
    """username변수로 사용자의 id를 가저옴"""
    rv = g.db.execute('select user_id from user where username = ?', [username]).fetchone()
    return rv[0] if rv else None

def format_datetime(timestamp):
    """시간 포맷 변형 함수"""
    return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d @ %H:%M")

def gravatar_url(email, size=80):
    """사용자의 email주소로 부터 gravatar 이미지 변환"""
    return 'http://www.gravatar.com/avatar/%s?d=identicon&s=%d' \
        %(md5(email.strip().lower().encode('utf-8')).hexdigest(), size)

@app.before_request
def before_request():
    """HTTP호출전에 실행되는 코드, DB를 연결하고 세션에 로그인이 되어있다면 
    user_id를 가져온다."""
    g.db = connect_db()
    g.user = None
    if 'user_id' in session:
        g.user = query_db('select * from user where user_id = ?', 
                          [session['user_id']], one=True)

@app.teardown_request
def teardown_request(exception):
    """HTTP호출 완료 후 실행하는 코드, db를 닫음"""
    if hasattr(g, 'db'):
        g.db.close()

@app.route('/')
def timeline():
    """사용자가 로그인 되어있다면 자신과 follows의 
    twit을 출력"""
    if not g.user:
        return redirect(url_for('public_timeline'))
    return render_template('timeline.html', messages=query_db('''
    select message.*, user.* from message, user
    where message.author_id = user.user_id and (
    user.user_id = ? or user.user_id in (select whom_id from follower where who_id = ?))
    order by message.pub_date desc limit ?''',
    [session['user_id'], session['user_id'], PER_PAGE]))

@app.route('/public')
def public_timeline():
    return render_template('timeline.html', messages=query_db('''
    select message.*, user.* from message, user
    where message.author_id = user.user_id
    order by message.pub_date desc limit ?''', [PER_PAGE]))

@app.route('/<username>')
def user_timeline(username):
    profile_user = query_db('select * from user where username=?',
                            [username], one=True)
    if profile_user is None:
        abort(404)
    
    followed = False

    if g.user:
        followed = query_db('''
            select 1 from follower 
            where follower.who_id = ? and follower.whom_id = ?''',
            [session['user_id'], profile_user['user_id']], one=True) is not None
            # followed가 없으면 정의하고, 없으면 False로 유지
    return render_template('timeline.html', messages=query_db('''
        select message.*, user.* from message, user
        where user.user_id = message.author_id and user.user_id = ?
        order by message.pub_date desc limit ?''',
        [profile_user['user_id'], PER_PAGE]), followed=followed, profile_user=profile_user)
         

@app.route('/register', methods=['GET', 'POST'])
def register():
    """회원가입, DB에 회원 데이터 저장"""
    if g.user:
        return redirect(url_for('timeline'))
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = 'You have to enter a username'
        elif not request.form['email'] or '@' not in request.form['email']:
            error = 'You have to enter a valid E-mail address'
        elif not request.form['password']:
            error = 'You have to enter a password'
        elif not request.form['password'] == request.form['password2']:
            error = 'Do not matches two passwords'
        elif get_user_id(request.form['username']) is not None:
            error = 'The username is already taken'
        else:
            g.db.execute('''
            insert into user(username, email, pw_hash) values (?, ?, ?)''',
            [request.form['username'], request.form['email'], 
             generate_password_hash(request.form['password'])])
            g.db.commit()
            flash('You were successfully registered and can login now')
            return redirect(url_for('login'))
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('/timeline'))
    error = None
    if request.method == 'POST':
        user = query_db('''
        select * from user where username = ?''',
        [request.form['username']], one=True) # login하려는 사용자 한 명의 데이터가 필요
                                              # 하기 때문에 one = True
        if user is None:
            error = 'Invalid username'
        elif not check_password_hash(user['pw_hash'], request.form['password']):
            error = 'Invalid password'

        else: #DB에도 입력정보가 있고, password도 맞는 경우 >>> 이미 로그인 상태
            flash('You were logged in')
            session['user_id'] = user['user_id']
            return redirect(url_for('timeline'))
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    flash('You were logged out')
    session.pop('user_id', None)
    return redirect(url_for('public_timeline'))

@app.route('/<username>/follow')
def follow_user(username):
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)
    g.db.execute('insert into follower (who_id, whom_id) values (?, ?)',
                 [session['user_id'], whom_id])
    g.db.commit()
    flash('You are now following "%s"' %whom_id)
    return redirect(url_for('user_timeline'), username=username)

@app.route('/<username>/unfollow')
def unfollow_user(username):
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)
    g.db.execute('delete from followed where who_id=? and whom_id=?',
                 [session['user_id'], whom_id])
    g.db.commit()
    flash('You are no longer following %s' %whom_id)
    return redirect(url_for('user_timeline'), username=username)

@app.route('/add_message', methods=['POST'])
def add_message():
    if 'user_id' not in session:
        abort(401)
    if request.form['text']:
        g.db.execute('''
        insert into message (author_id, text, pub_date)
        values (?,?,?)''',
        [session['user_id'], request.form['text'], int(time.time())])
        g.db.commit()
        flash('Your message was recorded')
    return redirect(url_for('timeline'))

@app.route('/threading_test')
def working():
    sec = 1
    #time.sleep(100)
    while 1:
        sec += 1
        print("working " + str(sec))
        time.sleep(1)
        if sec == 20:
            break
        
    return redirect(url_for('threading_done'))

@app.route('/threading_done')
def threading_done():
    
    return render_template('threading_done.html')

def work1(id, start, end, result):
    total = 0
    for i in range(start, end):
        total += i
        if i%100000 == 0:
            print('work1 done {0}: {1}'.format(i, total))
    result.append(total)
    return result

def work2(id, start, end, result):
    total = 0
    for i in range(start, end):
        if i%2 == 0:
            total += i
        if i%100000 == 0:
            print('work2 done {0}: {1}'.format(i, total))
    result.append(total)
    return result

# 신사2 필터 적용(html코드와 py코드 함수이름 동기화)
app.jinja_env.filters['datetimeformat'] = format_datetime
app.jinja_env.filters['gravatar'] = gravatar_url

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0')





