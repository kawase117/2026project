package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import org.json.JSONObject;
import java.time.LocalDate;

/** Add, edit and remove one-off and recurring hall events from the calendar. */
final class CalendarEventEditor {
    private static final String[] RULES={CalendarEventStore.ONCE,CalendarEventStore.WEEKLY,
        CalendarEventStore.MONTHLY_DAY,CalendarEventStore.MONTHLY_DD};
    private static final String[] RULE_LABELS={"単発（指定日）","毎週の曜日","毎月の指定日","毎月11日・22日"};
    private static final String[] WEEKDAYS={"月曜日","火曜日","水曜日","木曜日","金曜日","土曜日","日曜日"};
    private CalendarEventEditor(){}

    static void show(Activity activity,LedgerDb db,LocalDate selected,JSONObject existing,Runnable refresh){
        try{
            LinearLayout form=new LinearLayout(activity);form.setOrientation(1);form.setPadding(16,4,16,4);
            EditText hall=FormUi.compactChoice(activity,db,form,"ホール",existing==null?"":existing.optString("hall"),"hall",null,null);
            EditText title=FormUi.field(activity,form,"イベント名",existing==null?"":existing.optString("title"));
            title.setHint("例：ゾロ目日、取材、周年");
            FormUi.label(activity,form,"開催条件");
            Spinner rule=new Spinner(activity);rule.setContentDescription("開催条件");
            rule.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,RULE_LABELS));
            int initial=0;
            if(existing!=null)for(int i=0;i<RULES.length;i++)if(RULES[i].equals(existing.optString("rule")))initial=i;
            rule.setSelection(initial);form.addView(rule);
            LinearLayout singlePanel=new LinearLayout(activity);singlePanel.setOrientation(1);form.addView(singlePanel);
            EditText single=FormUi.date(activity,singlePanel,"開催日",existing!=null&&CalendarEventStore.ONCE.equals(existing.optString("rule"))?
                existing.optString("event_date"):selected.toString(),false);
            LinearLayout weeklyPanel=new LinearLayout(activity);weeklyPanel.setOrientation(1);form.addView(weeklyPanel);
            FormUi.label(activity,weeklyPanel,"曜日");
            Spinner weekday=new Spinner(activity);weekday.setContentDescription("曜日");
            weekday.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,WEEKDAYS));
            weekday.setSelection(existing!=null&&CalendarEventStore.WEEKLY.equals(existing.optString("rule"))?
                Math.max(0,Math.min(6,existing.optInt("weekday",1)-1)):selected.getDayOfWeek().getValue()-1);
            weeklyPanel.addView(weekday);
            LinearLayout monthlyPanel=new LinearLayout(activity);monthlyPanel.setOrientation(1);form.addView(monthlyPanel);
            EditText monthDay=FormUi.numeric(activity,monthlyPanel,"毎月の日付（1～31日）",
                Integer.toString(existing!=null&&CalendarEventStore.MONTHLY_DAY.equals(existing.optString("rule"))?
                    existing.optInt("day_of_month",selected.getDayOfMonth()):selected.getDayOfMonth()));
            LinearLayout periodPanel=new LinearLayout(activity);periodPanel.setOrientation(1);form.addView(periodPanel);
            EditText from=FormUi.date(activity,periodPanel,"繰り返し開始日",
                existing==null?selected.toString():existing.optString("starts_on",selected.toString()),false);
            EditText to=FormUi.date(activity,periodPanel,"終了日（任意）",
                existing==null||existing.isNull("ends_on")?"":existing.optString("ends_on"),true);
            FormUi.label(activity,periodPanel,"31日指定は、31日がない月には表示されません。");
            Runnable visibility=()->{
                int position=rule.getSelectedItemPosition();
                singlePanel.setVisibility(position==0?View.VISIBLE:View.GONE);
                weeklyPanel.setVisibility(position==1?View.VISIBLE:View.GONE);
                monthlyPanel.setVisibility(position==2?View.VISIBLE:View.GONE);
                periodPanel.setVisibility(position==0?View.GONE:View.VISIBLE);
            };
            rule.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
                public void onItemSelected(android.widget.AdapterView<?> p,View v,int pos,long id){visibility.run();}
                public void onNothingSelected(android.widget.AdapterView<?> p){}
            });visibility.run();
            ScrollView scroll=new ScrollView(activity);scroll.addView(form);
            AlertDialog.Builder builder=new AlertDialog.Builder(activity)
                .setTitle(existing==null?"イベントを登録":"イベントを編集")
                .setView(scroll).setNeutralButton("保存",null).setNegativeButton("戻る",null);
            if(existing!=null)builder.setPositiveButton("削除",null);
            AlertDialog dialog=builder.create();
            dialog.setOnShowListener(v->{
                dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(button->{
                    try{
                        int position=rule.getSelectedItemPosition();
                        JSONObject event=new JSONObject();
                        if(existing!=null)event.put("id",existing.getString("id"));
                        event.put("hall",hall.getText().toString().trim());
                        event.put("title",title.getText().toString().trim());
                        event.put("rule",RULES[position]);
                        if(position==0){String day=single.getText().toString();event.put("event_date",day).put("starts_on",day);}
                        else{
                            event.put("starts_on",from.getText().toString());
                            String until=to.getText().toString();if(!until.isEmpty())event.put("ends_on",until);
                            if(position==1)event.put("weekday",weekday.getSelectedItemPosition()+1);
                            if(position==2)event.put("day_of_month",AmountInput.signed(monthDay.getText().toString(),false));
                        }
                        new CalendarEventStore(db).save(event);
                        Catalog.add(db,"hall",event.getString("hall"));
                        dialog.dismiss();refresh.run();
                    }catch(Exception error){showError(activity,error);}
                });
                if(existing!=null)dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(button->
                    new AlertDialog.Builder(activity).setTitle("イベントを削除")
                        .setMessage(existing.optString("hall")+" ／ "+existing.optString("title")+"を削除しますか？")
                        .setNegativeButton("戻る",null).setPositiveButton("削除",(d,w)->{
                            new CalendarEventStore(db).delete(existing.optString("id"));dialog.dismiss();refresh.run();
                        }).show());
            });
            dialog.show();
        }catch(Exception error){showError(activity,error);}
    }
    private static void showError(Activity activity,Exception error){
        new AlertDialog.Builder(activity).setTitle("入力を確認してください")
            .setMessage(error.getMessage()).setPositiveButton("閉じる",null).show();
    }
}
