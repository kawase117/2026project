package jp.local.pachiboledger;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import org.json.JSONObject;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** User-entered hall events. Rules describe dates; they never change financial results. */
final class CalendarEventStore {
    static final String ONCE="once", WEEKLY="weekly", MONTHLY_DAY="monthly_day", MONTHLY_DD="monthly_dd";
    private static final String[] WEEKDAYS={"月","火","水","木","金","土","日"};
    private final LedgerDb ledger;
    CalendarEventStore(LedgerDb ledger){this.ledger=ledger;}

    static void createTables(SQLiteDatabase db){
        db.execSQL("CREATE TABLE IF NOT EXISTS calendar_events (id TEXT PRIMARY KEY NOT NULL, hall TEXT NOT NULL, title TEXT NOT NULL, rule TEXT NOT NULL, event_date TEXT, day_of_month INTEGER, weekday INTEGER, starts_on TEXT NOT NULL, ends_on TEXT)");
    }

    List<JSONObject> list() throws Exception {
        List<JSONObject> result=new ArrayList<>();
        try(Cursor c=ledger.getReadableDatabase().rawQuery("SELECT * FROM calendar_events ORDER BY hall,title,id",null)){
            while(c.moveToNext()){
                JSONObject row=new JSONObject();
                for(int i=0;i<c.getColumnCount();i++){
                    Object value=c.isNull(i)?JSONObject.NULL:c.getType(i)==Cursor.FIELD_TYPE_INTEGER?c.getLong(i):c.getString(i);
                    row.put(c.getColumnName(i),value);
                }
                result.add(row);
            }
        }
        return result;
    }

    String save(JSONObject event) throws Exception {
        String id=event.optString("id");if(id.isEmpty())id=UUID.randomUUID().toString();
        String hall=event.optString("hall").trim(),title=event.optString("title").trim();
        if(hall.isEmpty()||title.isEmpty())throw new IllegalArgumentException("ホールとイベント名を入力してください");
        String rule=event.optString("rule");
        if(!ONCE.equals(rule)&&!WEEKLY.equals(rule)&&!MONTHLY_DAY.equals(rule)&&!MONTHLY_DD.equals(rule))
            throw new IllegalArgumentException("開催条件を選択してください");
        LocalDate starts=LocalDate.parse(event.getString("starts_on"));
        String endText=event.optString("ends_on","");
        LocalDate ends=endText.isEmpty()?null:LocalDate.parse(endText);
        if(ends!=null&&ends.isBefore(starts))throw new IllegalArgumentException("終了日は開始日以降にしてください");
        String dateText=event.optString("event_date","");
        if(ONCE.equals(rule)){
            LocalDate single=LocalDate.parse(dateText);
            if(single.isBefore(starts)||(ends!=null&&single.isAfter(ends)))
                throw new IllegalArgumentException("単発の日付が開催期間外です");
        }
        long day=event.optLong("day_of_month");int weekday=event.optInt("weekday");
        if(MONTHLY_DAY.equals(rule)&&(day<1||day>31))throw new IllegalArgumentException("毎月の日付は1～31日で入力してください");
        if(WEEKLY.equals(rule)&&(weekday<1||weekday>7))throw new IllegalArgumentException("曜日を選択してください");
        ContentValues values=new ContentValues();
        values.put("id",id);values.put("hall",hall);values.put("title",title);values.put("rule",rule);
        if(ONCE.equals(rule))values.put("event_date",dateText);else values.putNull("event_date");
        if(MONTHLY_DAY.equals(rule))values.put("day_of_month",(int)day);else values.putNull("day_of_month");
        if(WEEKLY.equals(rule))values.put("weekday",weekday);else values.putNull("weekday");
        values.put("starts_on",starts.toString());
        if(ends==null)values.putNull("ends_on");else values.put("ends_on",ends.toString());
        ledger.getWritableDatabase().insertWithOnConflict("calendar_events",null,values,SQLiteDatabase.CONFLICT_REPLACE);
        return id;
    }

    void delete(String id){ledger.getWritableDatabase().delete("calendar_events","id=?",new String[]{id});}

    static boolean occurs(JSONObject event,LocalDate date){
        try{
            LocalDate starts=LocalDate.parse(event.getString("starts_on"));
            if(date.isBefore(starts))return false;
            String until=event.isNull("ends_on")?"":event.optString("ends_on","");
            if(!until.isEmpty()&&date.isAfter(LocalDate.parse(until)))return false;
            switch(event.getString("rule")){
                case ONCE:return date.equals(LocalDate.parse(event.getString("event_date")));
                case WEEKLY:return date.getDayOfWeek().getValue()==event.getInt("weekday");
                case MONTHLY_DAY:return date.getDayOfMonth()==event.getInt("day_of_month");
                case MONTHLY_DD:return date.getDayOfMonth()==11||date.getDayOfMonth()==22;
                default:return false;
            }
        }catch(Exception malformed){return false;}
    }

    static String description(JSONObject event){
        String rule=event.optString("rule");
        if(ONCE.equals(rule))return event.optString("event_date");
        if(WEEKLY.equals(rule))return "毎週"+WEEKDAYS[Math.max(0,Math.min(6,event.optInt("weekday")-1))]+"曜日";
        if(MONTHLY_DAY.equals(rule))return "毎月"+event.optInt("day_of_month")+"日";
        return "毎月11日・22日";
    }
}
