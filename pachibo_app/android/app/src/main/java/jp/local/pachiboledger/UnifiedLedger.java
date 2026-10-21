package jp.local.pachiboledger;

import org.json.JSONArray;
import org.json.JSONObject;
import java.math.BigInteger;
import java.util.*;

/** A common read model. Original records and session operations remain lossless in their own tables. */
final class UnifiedLedger {
    static final class Row {
        final String id,date,hall,machine,kind,number,memo,status,source,expenseHall,expenseMachine,workSource;
        final JSONArray tags;
        final BigInteger profit;
        final BigInteger investment,recovery;
        final Long spins,workYen;
        final boolean expense;
        final Long durationMinutes;
        final JSONObject original;
        final JSONObject workFields;
        Row(JSONObject original,boolean session,Accounting.Result result,JSONObject details)throws Exception {
            this(original,session,result,details,null);
        }
        Row(JSONObject original,boolean session,Accounting.Result result,JSONObject details,
            BigInteger[] flows)throws Exception {
            this.original=original;source=session?"session":"record";
            JSONObject fields=session?original.getJSONObject("metadata"):original;
            id=original.getString("id");date=original.getString("date");
            hall=fields.optString("hall");machine=fields.optString("machine");
            kind=session?fields.optString("game_kind","玉".equals(fields.optString("unit"))?"パチンコ":"スロット")
                :fields.optString("kind");
            number=fields.optString(session?"number":"machine_number");memo=fields.optString("memo");
            JSONArray sourceTags=fields.optJSONArray("tag_ids");tags=sourceTags==null?new JSONArray():sourceTags;
            expense=details.has("expense")?details.optBoolean("expense"):
                fields.optBoolean("expense",("雑費".equals(hall)&&"経費".equals(machine)));
            expenseHall=details.optString("expense_hall");expenseMachine=details.optString("expense_machine");
            long started=session?original.optLong("started_at",-1):details.optLong("started_at",-1);
            long ended=session?original.optLong("ended_at",-1):details.optLong("ended_at",-1);
            durationMinutes=(!session||fields.optBoolean("time_recorded",true))&&started>=0&&ended>started?
                (ended-started)/60000:null;
            spins=positiveOptional(details.has("spins")?details:fields,"spins");
            workFields=details.has("work_yen")?details:fields;
            workYen=signedOptional(workFields,"work_yen");
            workSource=workFields.optString("work_source",workYen==null?"":"manual");
            if(session){
                status="active".equals(original.optString("state"))?"active":result.evaluated==null?"unvalued":"complete";
                profit="complete".equals(status)?result.evaluated.roundYen():null;
            }else{
                status="pcb_type_missing".equals(original.optString("match_status"))?"review":"complete";
                profit="complete".equals(status)?BigInteger.valueOf(original.getLong("profit_yen")):null;
            }
            investment=profit==null?null:session?flows==null?null:flows[0]:
                original.has("investment_yen")?BigInteger.valueOf(original.getLong("investment_yen")):null;
            recovery=profit==null?null:session?flows==null?null:flows[1]:
                original.has("recovery_yen")?BigInteger.valueOf(original.getLong("recovery_yen")):null;
        }
        private static Long positiveOptional(JSONObject object,String key){
            if(!object.has(key)||object.isNull(key)||object.optString(key).isEmpty())return null;
            try{long value=Long.parseLong(object.get(key).toString());return value>=0?value:null;}
            catch(Exception ignored){return null;}
        }
        private static Long signedOptional(JSONObject object,String key){
            if(!object.has(key)||object.isNull(key)||object.optString(key).isEmpty())return null;
            try{return Long.parseLong(object.get(key).toString());}
            catch(Exception ignored){return null;}
        }
        JSONObject export()throws Exception {
            JSONObject row=new JSONObject().put("id",id).put("date",date).put("hall",hall)
                .put("kind",kind).put("machine",machine).put("machine_number",number)
                .put("memo",memo).put("tag_ids",tags).put("status",status).put("source_format",source)
                .put("profit_yen",profit==null?JSONObject.NULL:profit.toString())
                .put("expense",expense).put("expense_hall",expenseHall).put("expense_machine",expenseMachine)
                .put("duration_minutes",durationMinutes==null?JSONObject.NULL:durationMinutes)
                .put("investment_total_yen",investment==null?JSONObject.NULL:investment.toString())
                .put("recovery_total_yen",recovery==null?JSONObject.NULL:recovery.toString())
                .put("spins",spins==null?JSONObject.NULL:spins)
                .put("work_yen",workYen==null?JSONObject.NULL:workYen)
                .put("work_source",workSource);
            for(String key:new String[]{"work_equal_border","work_rotation_rate","work_holding_percent",
                "work_exchange_yen","work_exchange_balls"})
                row.put(key,workFields.has(key)?workFields.get(key):JSONObject.NULL);
            if("record".equals(source)){
                row.put("original_investment_yen",original.optLong("investment_yen"))
                    .put("original_recovery_yen",original.optLong("recovery_yen"))
                    .put("original_profit_yen",original.optLong("profit_yen"))
                    .put("source_item_id",original.optString("source_item_id"));
            }else{
                row.put("started_at",original.getLong("started_at"))
                    .put("ended_at",original.isNull("ended_at")?JSONObject.NULL:original.getLong("ended_at"));
            }
            return row;
        }
    }
    static final class Summary {
        BigInteger profit=BigInteger.ZERO;
        int count,active,review,unvalued;
        final Set<String> dates=new HashSet<>();
        void add(Row row){
            switch(row.status){
                case "complete":profit=profit.add(row.profit);count++;dates.add(row.date);break;
                case "active":active++;break;
                case "review":review++;break;
                default:unvalued++;break;
            }
        }
    }
    static List<Row> rows(LedgerDb db)throws Exception {
        List<Row> result=new ArrayList<>();
        Map<String,JSONObject> details=db.allRecordDetails();
        for(JSONObject row:db.records())result.add(new Row(row,false,null,
            details.getOrDefault(row.getString("id"),new JSONObject()),null));
        SessionStore store=new SessionStore(db);SessionStore.Snapshot snapshot=store.snapshot();
        for(JSONObject row:store.sessions()){
            String id=row.getString("id");
            Accounting.Result valued=snapshot.calculate(Collections.singleton(id));
            result.add(new Row(row,true,valued,new JSONObject(),
                valued.evaluated==null?null:sessionFlows(store,id)));
        }
        result.sort((a,b)->{
            int date=b.date.compareTo(a.date);return date!=0?date:b.id.compareTo(a.id);
        });
        return result;
    }
    /** Internal transfers are deliberately excluded: they are neither new stake nor payout. */
    private static BigInteger[] sessionFlows(SessionStore store,String id)throws Exception{
        Accounting.Amount in=new Accounting.Amount(0,1),out=new Accounting.Amount(0,1);
        for(JSONObject operation:store.details(id,false)){
            long delta=operation.getLong("delta");
            if(delta==0)continue;
            if(delta==Long.MIN_VALUE)return null;
            long magnitude=delta<0?-delta:delta;
            Accounting.Amount value="cash".equals(operation.getString("kind"))
                ?new Accounting.Amount(magnitude,1)
                :operation.isNull("rate_yen")?null:
                    new Accounting.Amount(operation.getLong("rate_yen"),operation.getLong("rate_units")).multiply(magnitude);
            if(value==null)return null;
            if(delta<0)in=in.add(value);else out=out.add(value);
        }
        return new BigInteger[]{in.roundYen(),out.roundYen()};
    }
    static Summary summary(Collection<Row> rows){Summary result=new Summary();for(Row row:rows)result.add(row);return result;}
    static JSONArray export(List<Row> rows)throws Exception {
        JSONArray result=new JSONArray();for(Row row:rows)result.put(row.export());return result;
    }
    static JSONArray export(List<Row> rows,Map<String,String> tagNames)throws Exception {
        JSONArray result=new JSONArray();
        for(Row row:rows){
            JSONObject item=row.export();List<String> names=new ArrayList<>();
            for(String id:TagPicker.ids(row.tags))names.add(tagNames.getOrDefault(id,id));
            item.put("tag_names",String.join(" | ",names));result.put(item);
        }
        return result;
    }
}
