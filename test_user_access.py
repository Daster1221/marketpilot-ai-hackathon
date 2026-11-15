import hashlib,hmac,json,tempfile,time,unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
import app,user_access as access,telegram_bot as bot,miniapp_api as api

class UserAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir();self.env=patch.dict(app.os.environ,{'TELEGRAM_OWNER_ID':'42000,99000','TELEGRAM_ADMIN_ID':'','TELEGRAM_BOT_TOKEN':'fixture-not-real'});self.env.start()
        bot.init_db();api.init_db()
    def tearDown(self):self.env.stop();self.root.stop();self.temp.cleanup()
    def signed(self,uid):
        data={'user':json.dumps({'id':uid,'username':'test_nick','first_name':'Тест'}),'auth_date':str(int(time.time()))}
        secret=hmac.new(b'WebAppData',b'fixture-not-real',hashlib.sha256).digest()
        data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
        return urlencode(data)
    def test_owner_grants_immediate_access_with_verified_username(self):
        with self.assertRaises(PermissionError):api.authenticate(self.signed(123456))
        access.grant(42000,'123456');self.assertIn('123456',bot.allowed_user_ids())
        self.assertEqual(api.authenticate(self.signed(123456)),123456)
        user=next(x for x in access.listing(42000)['users'] if x['id']==123456)
        self.assertEqual(user['username'],'test_nick');self.assertFalse(user['admin'])
        access.revoke(42000,123456)
        with self.assertRaises(PermissionError):api.authenticate(self.signed(123456))
    def test_members_cannot_escalate_or_read_user_list(self):
        for action in [lambda:access.grant(99000,'123456'),lambda:access.listing(99000),lambda:access.revoke(99000,42000)]:
            with self.assertRaises(PermissionError):action()
        self.assertNotIn('123456',bot.allowed_user_ids())
        with self.assertRaises(ValueError):access.revoke(42000,42000)
        with self.assertRaises(ValueError):access.grant(42000,'@fake_nick')
    def test_access_survives_initialization_and_names_update(self):
        access.grant(42000,'123456');bot.init_db();self.assertIn('123456',bot.allowed_user_ids())
        access.observe({'id':123456,'username':'old'});access.observe({'id':123456,'username':'new'})
        self.assertEqual(next(x for x in access.listing(42000)['users'] if x['id']==123456)['username'],'new')
