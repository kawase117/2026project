package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.view.Gravity;
import android.widget.*;
import org.json.JSONObject;
import java.math.BigInteger;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.BiConsumer;

/** One calendar total across imported and newly entered records. */
final class CalendarScreen {
    private final Activity activity;
    private final LedgerDb db;
    private final SessionStore store;
    private final BiConsumer<JSONObject,LocalDate> editLegacy;
    private final Consumer<LocalDate> startSession;
    private YearMonth month;
    private LocalDate selected;
    private LinearLayout root;
    private LinearLayout actionBar;
    private List<JSONObject> sessions;
    private List<JSONObject> events;
    private List<UnifiedLedger.Row> unified;

    CalendarScreen(Activity activity, LedgerDb db, BiConsumer<JSONObject,LocalDate> editLegacy, Consumer<LocalDate> startSession, LocalDate selected) {
        this.activity = activity; this.db = db; this.store = new SessionStore(db);
        this.editLegacy = editLegacy; this.startSession=startSession; this.selected = selected; this.month = YearMonth.from(selected);
    }
    private TextView text(String value, int size) {
        TextView view = new TextView(activity); view.setText(value); view.setTextSize(size);
        view.setPadding(6,12,6,12); view.setTextColor(FormUi.INK); return view;
    }
    private Button button(String value, Runnable action) {
        Button view = new Button(activity); FormUi.styleButton(view); view.setText(value); view.setOnClickListener(v -> action.run()); return view;
    }
    void render(LinearLayout root,LinearLayout actionBar) { this.root = root; this.actionBar=actionBar; draw(); }
    private void change(int delta) {
        month = month.plusMonths(delta); selected = month.atDay(1); draw();
    }
    private void draw() {
        try {
            sessions = store.sessions(); unified=UnifiedLedger.rows(db);
            events=new CalendarEventStore(db).list();root.removeAllViews();actionBar.removeAllViews();
            JSONObject ongoing=activeSession();
            Button action=ongoing==null?button(selected.getMonthValue()+"/"+selected.getDayOfMonth()+" の遊技を開始",()->startSession.accept(selected)):
                button("遊技中の台を終了・入力",()->finishActive(ongoing));
            action.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);
            action.setPadding(FormUi.dp(activity,16),0,0,0);
            actionBar.addView(action,new LinearLayout.LayoutParams(-1,FormUi.dp(activity,52)));
            LinearLayout controls = new LinearLayout(activity);
            controls.addView(button("‹", () -> change(-1)), new LinearLayout.LayoutParams(FormUi.dp(activity,52),FormUi.dp(activity,44)));
            TextView monthTitle=text(month.getYear()+"年 "+month.getMonthValue()+"月",20);
            monthTitle.setGravity(Gravity.CENTER_VERTICAL);
            controls.addView(monthTitle,new LinearLayout.LayoutParams(0,FormUi.dp(activity,44),1));
            controls.addView(button("今月", () -> { selected = LocalDate.now(); month = YearMonth.from(selected); draw(); }), new LinearLayout.LayoutParams(FormUi.dp(activity,64),FormUi.dp(activity,44)));
            controls.addView(button("›", () -> change(1)), new LinearLayout.LayoutParams(FormUi.dp(activity,52),FormUi.dp(activity,44)));
            root.addView(controls);
            TextView monthSummary=text(summary(month.toString()),15);monthSummary.setPadding(12,8,12,8);
            android.text.SpannableString colored=new android.text.SpannableString(monthSummary.getText());
            java.util.regex.Matcher amounts=java.util.regex.Pattern.compile("[+-][0-9,]+円").matcher(colored);
            while(amounts.find())colored.setSpan(new android.text.style.ForegroundColorSpan(colored.charAt(amounts.start())=='+'?FormUi.PLUS:FormUi.MINUS),amounts.start(),amounts.end(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            monthSummary.setText(colored);
            monthSummary.setBackground(FormUi.surface(FormUi.SURFACE,0));root.addView(monthSummary);
            LinearLayout weekdays = new LinearLayout(activity);
            for (String day : new String[]{"日","月","火","水","木","金","土"}) {
                TextView label = text(day,13); label.setGravity(Gravity.CENTER);label.setPadding(0,2,0,2);
                weekdays.addView(label,new LinearLayout.LayoutParams(0,-2,1));
            }
            root.addView(weekdays);
            int offset = month.atDay(1).getDayOfWeek().getValue() % 7;
            int count = ((offset + month.lengthOfMonth() + 6) / 7) * 7;
            LinearLayout week = null;
            for (int cell = 0; cell < count; cell++) {
                if (cell % 7 == 0) { week = new LinearLayout(activity); week.setBaselineAligned(false); root.addView(week); }
                int day = cell - offset + 1;
                if (day < 1 || day > month.lengthOfMonth()) {
                    week.addView(new TextView(activity),new LinearLayout.LayoutParams(0,-1,1)); continue;
                }
                LocalDate date = month.atDay(day); String key = date.toString();
                Button entry = button("", () -> { selected = date; draw(); });
                entry.setText(cellLabel(day,key));
                entry.setTextColor(FormUi.INK);
                entry.setTextSize(10); entry.setPadding(0,4,0,4); entry.setMinimumWidth(0); entry.setMinWidth(0);
                StringBuilder accessibility=new StringBuilder(key+" "+summary(key));
                for(JSONObject event:events)if(CalendarEventStore.occurs(event,date))
                    accessibility.append("。イベント ").append(event.optString("hall")).append(" ").append(event.optString("title"));
                entry.setContentDescription(accessibility.toString());
                entry.setMinHeight(FormUi.dp(activity,64));entry.setMinimumHeight(FormUi.dp(activity,64));
                entry.setBackgroundTintList(null);
                entry.setBackground(FormUi.surface(date.equals(selected)?FormUi.SELECTED:FormUi.SURFACE,date.equals(selected)?FormUi.ACCENT:FormUi.BORDER));
                if (date.equals(selected)) entry.setTypeface(null, android.graphics.Typeface.BOLD);
                LinearLayout.LayoutParams cellParams=new LinearLayout.LayoutParams(0,-1,1);cellParams.setMargins(2,3,2,3);week.addView(entry,cellParams);
            }
            root.addView(text(selected + " の明細",17)); root.addView(text(summary(selected.toString()),14));
            LinearLayout eventActions=new LinearLayout(activity);
            eventActions.addView(button("＋ イベント登録",()->CalendarEventEditor.show(activity,db,selected,null,this::draw)),
                new LinearLayout.LayoutParams(0,-2,1));
            eventActions.addView(button("登録済み一覧",this::showAllEvents),new LinearLayout.LayoutParams(0,-2,1));
            root.addView(eventActions);
            for(JSONObject event:events)if(CalendarEventStore.occurs(event,selected)){
                Button item=button(event.optString("hall")+" ／ "+event.optString("title")+"　"+CalendarEventStore.description(event),
                    ()->CalendarEventEditor.show(activity,db,selected,event,this::draw));
                item.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);root.addView(item);
            }
            root.addView(button("この日の記録を後から入力", () -> {
                try { editLegacy.accept(new JSONObject().put("date",selected.toString()).put("id","local-"+UUID.randomUUID()).put("tag_ids",new org.json.JSONArray()),selected); }
                catch (Exception e) { error(e); }
            }));
            for(UnifiedLedger.Row row:unified)if(selected.toString().equals(row.date)){
                String status=row.profit!=null?"収支 "+FormUi.money(row.profit):
                    "active".equals(row.status)?"遊技中":"review".equals(row.status)?"要確認・集計対象外":"計算待ち";
                String detail=row.hall+" ／ "+row.machine+" "+row.number+"番\n"+status
                    +"\nタグ："+TagPicker.display(db,row.tags)+"\n"+row.memo;
                root.addView(button(detail,()->{
                    if("session".equals(row.source))new SessionScreen(activity,db,this::draw).recordActions(row.original);
                    else editLegacy.accept(row.original,selected);
                }));
            }
        } catch (Exception e) { error(e); }
    }
    private JSONObject activeSession() {
        for(JSONObject row:sessions)if("active".equals(row.optString("state")))return row;
        return null;
    }
    private void finishActive(JSONObject row) {
        try {
            selected=LocalDate.parse(row.getString("date"));month=YearMonth.from(selected);
            SessionEditor.show(activity,db,selected,store.session(row.getString("id")),this::draw);
        }catch(Exception e){error(e);}
    }
    private UnifiedLedger.Summary totals(String prefix){
        UnifiedLedger.Summary summary=new UnifiedLedger.Summary();
        for(UnifiedLedger.Row row:unified)if(row.date.startsWith(prefix))summary.add(row);
        return summary;
    }
    private CharSequence cellLabel(int day,String prefix) {
        android.text.SpannableStringBuilder label=new android.text.SpannableStringBuilder(Integer.toString(day));
        int eventStart=label.length();
        LocalDate date=LocalDate.parse(prefix);
        for(JSONObject event:events)if(CalendarEventStore.occurs(event,date)){
            label.append(" ●");
            label.setSpan(new android.text.style.ForegroundColorSpan(FormUi.ACCENT),eventStart,label.length(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            break;
        }
        UnifiedLedger.Summary value=totals(prefix);
        if(value.count>0)appendAmount(label,"",value.profit);
        if(value.unvalued>0)label.append("\n計算待ち");
        if(value.active>0)label.append("\n遊技中");
        if(value.review>0)label.append("\n要確認");
        return label;
    }
    private void showAllEvents(){
        String[] labels=new String[events.size()];
        for(int i=0;i<events.size();i++){
            JSONObject event=events.get(i);
            labels[i]=event.optString("hall")+" ／ "+event.optString("title")+"　"+CalendarEventStore.description(event);
        }
        new AlertDialog.Builder(activity).setTitle("登録済みイベント")
            .setItems(labels,(dialog,which)->CalendarEventEditor.show(activity,db,selected,events.get(which),this::draw))
            .setPositiveButton("追加",(dialog,which)->CalendarEventEditor.show(activity,db,selected,null,this::draw))
            .setNegativeButton("閉じる",null).show();
    }
    private static void appendAmount(android.text.SpannableStringBuilder label,String prefix,BigInteger value){
        label.append("\n");int begin=label.length();label.append(prefix).append(FormUi.money(value).replace("円",""));
        label.setSpan(new android.text.style.ForegroundColorSpan(value.signum()>0?FormUi.PLUS:value.signum()<0?FormUi.MINUS:FormUi.MUTED),begin,label.length(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
    }
    private String summary(String prefix) {
        UnifiedLedger.Summary total=totals(prefix);
        String value=total.count==0?"確定収支はありません":"収支合計 "+total.count+"件 ／ "+FormUi.money(total.profit);
        if(total.active>0)value+="\n遊技中 "+total.active+"件（対象外）";
        if(total.unvalued>0)value+="\n計算待ち "+total.unvalued+"件（対象外）";
        if(total.review>0)value+="\n要確認 "+total.review+"件（対象外）";
        return value;
    }
    private void error(Exception e) { new AlertDialog.Builder(activity).setMessage(e.getMessage()).setPositiveButton("閉じる",null).show(); }
}
