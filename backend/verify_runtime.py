import shutil
import sqlite3

print('ffmpeg:', shutil.which('ffmpeg'))
conn = sqlite3.connect('ivr_verification.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info('call_sessions')")
cols = [r[1] for r in cur.fetchall()]
print('language_col_present:', 'language' in cols)
