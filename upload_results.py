import json
import socket
import requests
from datetime import datetime
from io import StringIO

import pandas as pd

import subprocess

# Mail support

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import premailer

import graphitesend

###########
## CONFIG #
###########

GIST_URL = 'https://api.github.com'
SMTP_PORT = 587

try:
    from config import *
except:
    print("Please create a config.py file containing:\n{}".format('\n'.join(['GRAPHITE_SERVER', 'GIST_USER', 'GIST_API_TOKEN', 'MAIL_SENDER', 
                                                                             'MAIL_RECEIVER', 'SMTP_SERVER', 'SMTP_PASSWORD'])))
###########
#
# -> A simple gist class
#
###########

class Gist:
    def __init__(self, user=None, api_token=None):
        self.user = user
        self.header = {'Content-Type': 'application/json'}
        if user and api_token:
            self.header['X-Github-Username'] = user
            self.header['Authorization'] = f'token {api_token}'

    def list(self):
        url = f'{GIST_URL}/users/{self.user}/gists'
        return requests.get(url, headers=self.header).json()

    def by_id(self, gist_id):
        url = f'{GIST_URL}/gists/{gist_id}'
        return requests.get(url, headers=self.header).json()

    def create(self, name='', description='', files={}, public=True):
        url = f'{GIST_URL}/gists'
        data = {"description": description, "public": public, "files": files}
        r = requests.post(url, data=json.dumps(data), headers=self.header)
        if r.status_code == 201:
            return r
        raise Exception('Gist not created: server response was [%s] %s' %
                        (r.status_code, r.text))

    def edit(self, gist_id, edit):
        url = f'{GIST_URL}/gists/{gist_id}'
        r = requests.patch(url, data=json.dumps(edit), headers=self.header)
        if r.status_code < 300:
            return r
        raise Exception('Gist not edited: server response was [%s] %s' %
                        (r.status_code, r.text))

###########

header_template = """
╒════════════════════════════════════════════════════════════════════════════╕
│░░░░{:^68s}░░░░│
╘════════════════════════════════════════════════════════════════════════════╛\n
"""

def get_meta_triplet():
    hostname = socket.gethostname()
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip().decode('utf-8')
    commit = subprocess.check_output(
        ["git", "rev-parse",
         "HEAD"]).decode('utf-8')
    return hostname, branch, commit

def get_meta_info(add_meta_data="\n\n\n\n\n"):

    hostname, branch, commit = get_meta_triplet()
        
    meta_data = """{header}
    Date:               {date}
    Benchmark Machine:  {hostname}
    CPU:                {CPU}
    Branch:             {branch}
    Full commit hash:   {commit}\n

Warnings:\n{meta_data}
    """.format(
        header=header_template.format(hostname + ", " + branch + ", " + commit[0:10]),
        hostname=hostname,
        branch=branch,
        commit=commit,
        CPU=add_meta_data.split('\n')[0].strip(),
        date=add_meta_data.split('\n')[1].strip(),
        meta_data=add_meta_data
    )

    meta_data += header_template.format("CPU INFO")
    with open('/proc/cpuinfo') as fi:
        meta_data += fi.read()

    description = "{hostname}_{branch}".format(
        hostname=hostname,
        branch=branch
    )

    return meta_data, description

def send_mail(recipient, cc, plain, html=''):
    # Create message container - the correct MIME type is multipart/alternative.
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "xtensor benchmark results for " + get_meta_info()[1]
    msg['From'] = MAIL_SENDER
    msg['To'] = recipient

    part1 = MIMEText(plain, 'plain')
    msg.attach(part1)

    if html:
        part2 = MIMEText(html, 'html')
        msg.attach(part2)

    session = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    session.starttls()
    session.login(MAIL_SENDER, SMTP_PASSWORD)

    session.sendmail(MAIL_SENDER, recipient, msg.as_string())
    session.quit()

def send_graphite(df, benchdate):
    hostname, branch, commit = get_meta_triplet()
    # graphite data is prefixed with {hostname}.{branch}
    print(header_template.format(f"Beginning Upload for: {hostname}.{branch}"))

    g = graphitesend.init(graphite_server=GRAPHITE_SERVER, prefix=f"{hostname}.{branch}", system_name='')
    for name, row in df.iterrows():
        idx = name.find('_')
        if idx:
            name = list(name); name[idx] = '.'; name = ''.join(name)
        print("Uploading: {}, {}, timestamp: {}".format(name, row.cpu_time, benchdate.timestamp()))
        g.send(name, row['cpu_time'], timestamp=benchdate.timestamp())

def main():

    print(header_template.format("Uploading ... "))

    gist = Gist(user=GIST_USER, api_token=GIST_API_TOKEN)

    bench_results = ""
    add_meta_data = ""

    with open('results.csv') as fi:
        cpy = False
        for line in fi:

            if line.startswith("name,iterations,real_time,cpu_time"):
                cpy = True

            if cpy:
                bench_results += line
            else:
                add_meta_data += line
                if line.startswith("20"):
                    benchdate = datetime.strptime(line.strip(), '%Y-%m-%d %H:%M:%S')
                    print("The date is: ", benchdate)


    meta_data, description = get_meta_info(add_meta_data)

    # List down all the names of authenticated user's Gists
    all_gists = gist.list()

    master_gist = None

    compare_descr = f'{socket.gethostname()}_master'
    for d in all_gists:
        if d['description'].startswith(compare_descr):
            master_gist = d
            break

    if master_gist:
        master_gist_id = master_gist['id']

        files = gist.by_id(master_gist_id)['files']
        last_meta = files['meta_data.txt']['content']
        last_results = files['bench_results.csv']['content']

        df_current_results = pd.read_csv(StringIO(bench_results), index_col=0)
        df_last_results = pd.read_csv(StringIO(last_results), index_col=0)
        perc_change = (
            df_current_results[['cpu_time']] - df_last_results[['cpu_time']]
        ) / df_last_results[['cpu_time']]
        df_current_results['difference_master'] = perc_change

        headers = list(df_current_results)
        headers.remove('difference_master')
        headers.insert(headers.index('time_unit') + 1, 'difference_master')
        df_current_results = df_current_results[headers]
        print(header_template.format("RESULTS"))
        bench_results = df_current_results.to_csv(float_format='%.3f')
        print(df_current_results[['cpu_time', 'difference_master']])

    else:
        print(header_template.format("RESULTS"))
        print(df_current_results[['cpu_time']])

    update_gist = None
    for d in all_gists:
        if d['description'].startswith(description):
            update_gist = d
            break

    if update_gist:
        r = gist.edit(
            update_gist['id'], 
            {'files':
                {
                    'bench_results.csv': {
                        'content': bench_results
                    },
                    'meta_data.txt': {
                        'content': meta_data
                    }
                }
            }
        )
    else:
        gist.create(
            name='bench_results',
            description=get_desired_filename(),
            public=True,
            files={
                'bench_results.csv': {
                    'content': bench_results
                },
                'meta_data.txt': {
                    'content': meta_data
                }
            }
        )

    print(header_template.format("SENDING TO GRAPHITE"))
    send_graphite(df_current_results, benchdate)

    print(header_template.format("SENDING EMAIL"))

    def color_negative_red(val):
        max_perc = 0.5
        color = 'rgba(255, 0, 0, 1)' if val < 0 else 'rgba(0, 255, 0, 1)'
        return 'color: %s' % color

    if 'difference_master' in list(df_current_results):
        html = df_current_results[['iterations', 'real_time', 'cpu_time', 'difference_master', 'time_unit']]
        html = html.style.applymap(color_negative_red, subset=['difference_master'])
    else:
        html = df_current_results[['iterations', 'real_time', 'cpu_time', 'time_unit']]
    html = html.set_properties(**{'text-align': 'right'})        
    html = premailer.transform(html.render())

    send_mail(MAIL_RECEIVER[0], [],
        df_current_results[['iterations', 'real_time', 'cpu_time', 'difference_master', 'time_unit']].to_csv(float_format='%.3f'),
        html
    )

    print(header_template.format("DONE"))

if __name__ == '__main__':
    main()