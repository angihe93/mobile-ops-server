from flask import Flask,jsonify, request
import datetime
import os
import psycopg2
import json
# from psycopg2.extras import RealDictCursor,DictCursor
from datetime import date, datetime, timedelta, timezone
from flask_jwt_extended import create_access_token,get_jwt,get_jwt_identity, unset_jwt_cookies, jwt_required, JWTManager

x = datetime.now()

# Initializing flask app
app = Flask(__name__)

app.config["JWT_SECRET_KEY"] = os.environ.get('JWT_SECRET_KEY')
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
jwt = JWTManager(app)

host = os.environ.get('DB_HOST')
database = os.environ.get('DB_DB')
user = os.environ.get('DB_USER')
password = os.environ.get('DB_PW')

ops_username = os.environ.get('OPS_USERNAME')
ops_password = os.environ.get('OPS_PASSWORD')

def get_db_connection():
    conn = psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=password)
    return conn

@app.after_request
def refresh_expiring_jwts(response):
    try:
        exp_timestamp = get_jwt()["exp"]
        now = datetime.now(timezone.utc)
        target_timestamp = datetime.timestamp(now + timedelta(minutes=30))
        if target_timestamp > exp_timestamp:
            access_token = create_access_token(identity=get_jwt_identity())
            data = response.get_json()
            if type(data) is dict:
                data["access_token"] = access_token 
                response.data = json.dumps(data)
        return response
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original respone
        return response

@app.route('/token', methods=["POST"])
def create_token():
    email = request.json.get("email", None)
    password = request.json.get("password", None)

    if email != ops_username or password != ops_password:
        return {"msg": "Wrong email or password"}, 401

    access_token = create_access_token(identity=email)
    response = {"access_token":access_token}
    return response

@app.route("/logout", methods=["POST"])
def logout():
    response = jsonify({"msg": "logout successful"})
    unset_jwt_cookies(response)
    return response

@app.route('/tasks', methods=['GET'])
@jwt_required()
def show_tasks():
    conn = get_db_connection()
    # cur = conn.cursor(cursor_factory=DictCursor) #RealDictCursor
    today=str(date.today().strftime("%Y-%m-%d"))
    print(today)
    cur = conn.cursor()
    # cur.execute("""select cast(dt_sched as varchar), notes, timeslots, renter_id, address_num, address_street, address_apt, address_zip, cast(chosen_time as varchar) from logistics""")
    # dropoffs:
    cur.execute(f"""
        select 'Dropoff' as type, replace(users.name,',',' ') as name, 
        logistics.dt_sched, logistics.notes, logistics.renter_id, 
        coalesce(cast(logistics.chosen_time as varchar),logistics.timeslots) as time,
        logistics.address_num, logistics.address_street, logistics.address_apt, logistics.address_zip,
        logistics.address_num || ' ' || logistics.address_street || ', NY ' || logistics.address_zip as address,
        users.email, profiles.phone,
        order_dropoffs.order_id, cast(orders.res_date_start as varchar) as date, '#' || items.id || ', ' || items.name || ' (@ ' || items.address_num || ' ' || items.address_street || ', NY ' || items.address_zip || ')' as items
        from logistics
        left join users on logistics.renter_id=users.id
        left join profiles on users.id=profiles.id
        left join order_dropoffs on logistics.dt_sched=order_dropoffs.dt_sched and logistics.renter_id=order_dropoffs.renter_id
        left join orders on order_dropoffs.order_id=orders.id
        left join items on orders.item_id=items.id
        where res_date_start>='{today}' and timeslots is not null
        order by res_date_start, time
    """)
    columns = [desc[0] for desc in cur.description] #https://stackoverflow.com/a/54228841/19228216
    # print(columns)
    dropoff_rows=cur.fetchall()
    dropoff_rows = [list(i) for i in dropoff_rows]
    # dropoff_rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    # dropoff_rows = cur.fetchall()
    # combine if same user has multiple items

    # pickups (note extensions and early returns, early returns should be covered in orders or extensions depending on which is more recent):
    cur.execute(f"""
        select 'Pickup' as type, replace(users.name,',',' ') as name, 
        logistics.dt_sched, logistics.notes, logistics.renter_id, 
        coalesce(cast(logistics.chosen_time as varchar),logistics.timeslots) as time,
        logistics.address_num, logistics.address_street, logistics.address_apt, logistics.address_zip,
        logistics.address_num || ' ' || logistics.address_street || ', NY ' || logistics.address_zip as address,
        users.email, profiles.phone,
        order_pickups.order_id, cast(orders.res_date_end as varchar) as date, '#' || items.id || ', ' || items.name as items
        from logistics
        left join users on logistics.renter_id=users.id
        left join profiles on users.id=profiles.id
        left join order_pickups on logistics.dt_sched=order_pickups.dt_sched and logistics.renter_id=order_pickups.renter_id
        left join orders on order_pickups.order_id=orders.id
        left join items on orders.item_id=items.id
        where timeslots is not null and order_pickups.order_id>1000
        order by res_date_end, time
    """) # don't require res date end > today since there may be extensions that are > today
    # need order_id > 1000 because jump in order_id to 7000, no extensions for order_id<=1000 would cause res date end to >= today
    pickup_rows = cur.fetchall()
    # columns = [desc[0] for desc in cur.description]
    pickup_rows = [list(i) for i in pickup_rows]

    cur.execute("select extensions.order_id, cast(extensions.res_date_start as varchar), cast(extensions.res_date_end as varchar) from extensions")
    extensions = cur.fetchall()
    
    print(type(pickup_rows[0]))
    print(pickup_rows[0])
    print(pickup_rows[0][-2])
    # print(pickup_rows[0]['order_id'])
    # print(pickup_rows[0].values()[1])

    for p in pickup_rows:
        e = [e[2] for e in extensions if e[0]==p[-3]] # add extension res date end to e if order_id is the same
        if len(e)>0:
            e.sort()
            p[-2] = e[-1] # update res date end

    # # get pickup_rows with res_date_end>today:
    # print(pickup_rows[0])
    # print(pickup_rows[0][-2])
    # print(type(pickup_rows[0][-2]))
    pickup_rows = [i for i in pickup_rows if i[-2]>=today]
    # print('pickup_rows after mod')
    # print(pickup_rows)
    
    # pickup_rows = [dict(zip(columns, row)) for row in pickup_rows]
    all_tasks=dropoff_rows
    all_tasks.extend(pickup_rows)
    for t in all_tasks:
        t[-3] = [t[-3]] # make id field a list
    all_tasks = sorted(all_tasks, key=lambda x: (x[-2], x[-5], x[5])) # sort by date, email, time

    # add up items and task ids for the same user for the same task
    prev_email = all_tasks[0][-5]
    prev_type = all_tasks[0][0]
    prev_day = all_tasks[0][-2]
    i = 1
    length = len(all_tasks)
    while i < length:
        if all_tasks[i][-5]==prev_email and all_tasks[i][0]==prev_type and all_tasks[i][-2]==prev_day:
            prev_email = all_tasks[i][-5]
            prev_type = all_tasks[i][0]
            prev_day = all_tasks[i][-2]
            all_tasks[i-1][-1] += '; '+all_tasks[i][-1]
            all_tasks[i-1][-3].append(all_tasks[i][-3][0])
            del all_tasks[i]
        elif all_tasks[i][-5]!=prev_email or all_tasks[i][0]!=prev_type or all_tasks[i][-2]!=prev_day:
            prev_email = all_tasks[i][-5]
            prev_type = all_tasks[i][0]
            prev_day = all_tasks[i][-2]
            i+=1
        length = len(all_tasks)

    all_tasks = sorted(all_tasks, key=lambda x: (x[-2], x[5], x[-5])) # sort by date, time, email
    ### todo: process itrems: replace , separating items with ;, remove trailing comma, add item links, and item locations for dropoffs

    all_tasks = [dict(zip(columns, row)) for row in all_tasks]
# do queue view first
#     For couriers: 
 # could use the query in auto_ops/app.py calendar()
    # in react native, separate upcoming and past tasks to different pages
    # 
    # task date, 
    # 
    # task link, 
    # task type (pickup/dropoff), 
    # other couriers assigned to the task (if any), 
    # renter name, 
    # renter address, 
    # renter email, 
    # renter phone, 
    # renter notes, 
    # item name & id (with link and pictures), 
    # detailed current item location if type is dropoff, 
    # scheduled time, 
    # map of task locations for a specified period, 
    # reminder to mark yes for each task in google calendar if hasn’t done so, 
    # form to mark task complete if task has not been completed (
    # for dropoffs, just a checkbox to say task has been completed and an optional text input entry to leave other comments, eg. item broken and replaced with x. 
    # For pickups, a checkbox to say task has been completed and checkbox to indicate current item location, and an optional text input entry to leave other comments),
    # Have an option to show historical/completed tasks as well? If need to reference those for any reason

    # return jsonify(cur.fetchmany(10))
    # return jsonify(cur.fetchall())
    # return jsonify(dropoff_rows)
    # return jsonify(pickup_rows)
    return jsonify(all_tasks)


@app.route('/updateitem/<id>/<location>', methods=['GET','POST','PUT'])
@jwt_required()
def update_item_location(id,location):
    conn = get_db_connection()
    cur = conn.cursor()
    location_dict = {'cu':['108','W 107th St', '2-12-16','10025'], #  Unit 2-12-16
                    'csl':['69','Charlton St','','10014']}
    update_sql = f"""update items set 
                    address_num={location_dict[location][0]},
                    address_street='{location_dict[location][1]}',
                    address_apt='{location_dict[location][2]}',
                    address_zip='{location_dict[location][3]}'
                    where id={id}"""
    
    cur.execute(update_sql)
    conn.commit()
    # verify:
    cur.execute(f"""select * from items where id={id}""")
    row = cur.fetchone()
    item_updated = dict(zip([desc[0] for desc in cur.description], row))

    cur.close()
    # item = cur.fetchone()
    # print(item)
    return jsonify(item_updated)

@app.route('/showitem/<id>',methods=['GET'])
@jwt_required()
def show_item(id):
        conn = get_db_connection()
        cur = conn.cursor()
        try: 
            cur.execute(f"""select * from items where id={id}""")
            row=cur.fetchone()
            return jsonify(dict(zip([desc[0] for desc in cur.description], row)))
        except:
            return ""

@app.route('/marktaskcomplete/<id>', methods=['GET','POST']) # need order id(s) and type dropoff or pickup
def mark_task_complete(id):
    return ""

# Running app
if __name__ == '__main__':
	app.run(host='192.168.1.70',port=3000,debug=True)
    # app.run(host='160.39.11.146',port=3000,debug=True) 
    # use ip address rather than local host, otherwise will get network request error
    # to find ip address, go to System Preferences > Network and select your connection in the left sidebar. Then click Advanced > TCP/IP


