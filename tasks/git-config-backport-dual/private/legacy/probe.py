import io,json,sys
sys.path.insert(0,'/workspace')
import configparser as cp
import service
p=cp.ConfigParser();p.read_dict({'second':{'z':'9','a':'1'},'first':{'c':'3'}})
out=io.StringIO();status=service.export(p,out)
safe=[out.getvalue(),status,type(status).__name__]
p.set('first','bad\rkey','value');out=io.StringIO('retain');out.seek(0,2)
status=service.export(p,out)
print(json.dumps({'safe':safe,'invalid':[status,type(status).__name__,out.getvalue(),out.tell(),out.closed]}))
