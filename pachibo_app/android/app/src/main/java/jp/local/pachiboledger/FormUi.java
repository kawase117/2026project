package jp.local.pachiboledger;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.text.*;
import android.widget.*;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.math.BigInteger;
import java.util.*;

final class FormUi {
    static int INK, ACCENT, PLUS, MINUS, MUTED, BG, SURFACE, SELECTED, BORDER, GRID, LINE;
    static void configure(boolean dark) {
        INK=Color.parseColor(dark?"#ECF3F6":"#1E3041");
        ACCENT=Color.parseColor(dark?"#74D9D0":"#12666B");
        PLUS=Color.parseColor(dark?"#78DDB6":"#006F64");
        MINUS=Color.parseColor(dark?"#FF8F9B":"#B63141");
        MUTED=Color.parseColor(dark?"#A5B7C3":"#5B6A78");
        BG=Color.parseColor(dark?"#111A20":"#F5F7FA");
        SURFACE=Color.parseColor(dark?"#223039":"#FFFFFF");
        SELECTED=Color.parseColor(dark?"#254A4B":"#DEEFEE");
        BORDER=Color.parseColor(dark?"#40545D":"#E8EDF2");
        GRID=Color.parseColor(dark?"#667985":"#BBBBBB");
        LINE=Color.parseColor(dark?"#81B9FF":"#1769AA");
    }
    static int dp(Context c,int value) { return Math.round(value*c.getResources().getDisplayMetrics().density); }
    static GradientDrawable surface(int color,int stroke) {
        GradientDrawable d=new GradientDrawable(); d.setColor(color); d.setCornerRadius(16); if(stroke!=0)d.setStroke(2,stroke); return d;
    }
    static void styleButton(Button b) {
        b.setAllCaps(false); b.setTextColor(ACCENT);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(SURFACE));
        b.setOnTouchListener((view,event)->{
            if(event.getActionMasked()==MotionEvent.ACTION_DOWN && view.isEnabled())
                view.performHapticFeedback(android.os.Build.VERSION.SDK_INT>=30?
                    HapticFeedbackConstants.CONFIRM:HapticFeedbackConstants.VIRTUAL_KEY);
            return false;
        });
    }
    static String money(BigInteger value) { return (value.signum()>0 ? "+" : "")+String.format(Locale.JAPAN,"%,d",value)+"円"; }
    static void tint(TextView text,BigInteger value) { text.setTextColor(value.signum()>0 ? PLUS : value.signum()<0 ? MINUS : MUTED); }
    static TextView label(Context c,LinearLayout panel,String title) {
        TextView t=new TextView(c);t.setText(title); t.setTextColor(INK); t.setTextSize(14); t.setPadding(8,16,8,6);panel.addView(t);return t;
    }
    static EditText field(Activity a,LinearLayout panel,String title,String value) {
        label(a,panel,title); EditText e=new EditText(a);e.setSingleLine(true);e.setText(value);e.setTextSize(16);e.setContentDescription(title);panel.addView(e);return e;
    }
    static EditText numeric(Activity a,LinearLayout panel,String title,String value) {
        EditText e=field(a,panel,title,value); numeric(e);return e;
    }
    static EditText machineNumber(Activity a,LinearLayout panel,String title,String value){
        EditText e=field(a,panel,title,value);
        machineNumber(e);
        return e;
    }
    static void machineNumber(EditText e){
        e.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        e.setKeyListener(android.text.method.DigitsKeyListener.getInstance("0123456789０１２３４５６７８９"));
        e.setFilters(new InputFilter[]{(source,start,end,dest,dstart,dend)->{
            StringBuilder accepted=new StringBuilder();
            for(int i=start;i<end;i++)if("0123456789０１２３４５６７８９".indexOf(source.charAt(i))>=0)accepted.append(source.charAt(i));
            return accepted.length()==end-start?null:accepted.toString();
        }});
    }
    static String numberText(EditText e){
        String value=java.text.Normalizer.normalize(e.getText().toString().trim(),java.text.Normalizer.Form.NFKC);
        if(!value.isEmpty()&&!value.matches("[0-9]+"))throw new IllegalArgumentException("台番号は数字で入力してください");
        return value;
    }
    static void numeric(EditText e) {
        e.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        // Keep a numeric keyboard and reject letters, while accepting full-width pasted digits.
        e.setKeyListener(android.text.method.DigitsKeyListener.getInstance("0123456789０１２３４５６７８９,， 　"));
        e.setRawInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        e.setFilters(new InputFilter[]{(source,start,end,dest,dstart,dend)->{
            StringBuilder accepted=new StringBuilder();
            for(int i=start;i<end;i++)if("0123456789０１２３４５６７８９,， 　".indexOf(source.charAt(i))>=0)accepted.append(source.charAt(i));
            return accepted.length()==end-start?null:accepted.toString();
        }});
        e.addTextChangedListener(new TextWatcher(){ boolean changing;
            public void beforeTextChanged(CharSequence s,int start,int count,int after){}
            public void onTextChanged(CharSequence s,int start,int before,int count){}
            public void afterTextChanged(Editable text){
                if(changing)return;
                String plain=AmountInput.normalize(text.toString()); if(!plain.matches("[0-9]+"))return;
                int cursor=Math.max(0,e.getSelectionStart());
                int digits=AmountInput.normalize(text.toString().substring(0,Math.min(cursor,text.length()))).length();
                String grouped=String.format(Locale.US,"%,d",new BigInteger(plain));
                if(grouped.equals(text.toString()))return;
                changing=true; e.setText(grouped); int position=0,seen=0;
                while(position<grouped.length() && seen<digits){if(Character.isDigit(grouped.charAt(position)))seen++;position++;}
                e.setSelection(position);changing=false;
            }
        });
        e.setText(e.getText().toString());
    }
    static void conversion(Activity a,LinearLayout panel,EditText quantity,EditText yen,EditText units){
        TextView preview=label(a,panel,"");
        Runnable update=()->{try{
            long count=AmountInput.signed(quantity.getText().toString(),false);
            BigInteger converted=BigInteger.ZERO;
            if(count!=0){long y=AmountInput.signed(yen.getText().toString(),false),u=AmountInput.signed(units.getText().toString(),false);
                if(y<=0||u<=0)throw new IllegalArgumentException();converted=new Accounting.Amount(y,u).multiply(count).roundYen();}
            preview.setText("この数量の円換算："+String.format(Locale.JAPAN,"%,d円",converted)+"（1円未満は四捨五入）");preview.setTextColor(ACCENT);
        }catch(Exception e){preview.setText("数量と交換率を入力すると、円換算を表示します");preview.setTextColor(MUTED);}};
        TextWatcher watcher=new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}public void onTextChanged(CharSequence s,int st,int b,int c){update.run();}public void afterTextChanged(Editable s){}};
        for(EditText e:new EditText[]{quantity,yen,units})e.addTextChangedListener(watcher);update.run();
    }
    static EditText date(Activity a,LinearLayout panel,String title,String value,boolean clearable) {
        EditText e=field(a,panel,title,value);e.setFocusable(false);e.setHint(clearable?"指定なし・タップして選択":"タップして選択");
        e.setOnClickListener(v->{
            LocalDate initial;try{initial=LocalDate.parse(e.getText().toString());}catch(Exception ignored){initial=LocalDate.now();}
            DatePickerDialog d=new DatePickerDialog(a,(p,y,m,day)->e.setText(LocalDate.of(y,m+1,day).toString()),initial.getYear(),initial.getMonthValue()-1,initial.getDayOfMonth());
            if(clearable)d.setButton(DialogInterface.BUTTON_NEUTRAL,"指定を解除",(x,w)->e.setText(""));d.show();
        }); return e;
    }
    static EditText time(Activity a,LinearLayout panel,String title,String value) {
        EditText e=field(a,panel,title,value);e.setFocusable(false);e.setHint("タップして選択");
        e.setOnClickListener(v->{ LocalTime now;try{now=LocalTime.parse(e.getText().toString());}catch(Exception ignored){now=LocalTime.now();}
            new TimePickerDialog(a,(p,h,m)->e.setText(String.format(Locale.JAPAN,"%02d:%02d",h,m)),now.getHour(),now.getMinute(),true).show();
        });
        Button current=new Button(a);current.setText("現在時刻を入力");styleButton(current);panel.addView(current);
        current.setOnClickListener(v->e.setText(LocalTime.now().format(DateTimeFormatter.ofPattern("HH:mm"))));
        return e;
    }
    static EditText compactTime(Activity a,LinearLayout panel,String title,String value,boolean clearable) {
        LinearLayout row=new LinearLayout(a);row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView caption=new TextView(a);caption.setText(title.startsWith("開始")?"開始":"終了");
        caption.setTextColor(INK);caption.setTextSize(15);
        row.addView(caption,new LinearLayout.LayoutParams(dp(a,48),-2));
        EditText e=new EditText(a);e.setSingleLine(true);e.setText(value);e.setTextSize(16);
        e.setContentDescription(title);e.setHint("時刻");e.setFocusable(false);
        e.setOnClickListener(v->{LocalTime initial;
            try{initial=LocalTime.parse(e.getText().toString());}catch(Exception ignored){initial=LocalTime.now();}
            new TimePickerDialog(a,(p,h,m)->e.setText(String.format(Locale.JAPAN,"%02d:%02d",h,m)),
                initial.getHour(),initial.getMinute(),true).show();
        });
        row.addView(e,new LinearLayout.LayoutParams(0,dp(a,48),1));
        Button current=new Button(a);current.setText("現在");current.setContentDescription(title+"に現在時刻を入力");
        styleButton(current);row.addView(current,new LinearLayout.LayoutParams(dp(a,62),dp(a,44)));
        current.setOnClickListener(v->e.setText(LocalTime.now().format(DateTimeFormatter.ofPattern("HH:mm"))));
        if(clearable){Button clear=new Button(a);clear.setText("消去");clear.setContentDescription("終了時刻を空欄にする");
            styleButton(clear);row.addView(clear,new LinearLayout.LayoutParams(dp(a,62),dp(a,44)));
            clear.setOnClickListener(v->e.setText(""));}
        panel.addView(row);return e;
    }
    static EditText compactChoice(Activity a,LedgerDb db,LinearLayout panel,String title,String value,String kind,
                                  java.util.function.Supplier<String> gameKind,java.util.function.Supplier<String> hall) {
        LinearLayout row=new LinearLayout(a);row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        Button choose=new Button(a);choose.setText(title);choose.setContentDescription(title+"を一覧から選択");styleButton(choose);
        row.addView(choose,new LinearLayout.LayoutParams(dp(a,78),dp(a,44)));
        EditText e=new EditText(a);e.setSingleLine(true);e.setText(value);e.setTextSize(16);
        e.setHint(title+"名");e.setContentDescription(title);
        row.addView(e,new LinearLayout.LayoutParams(0,dp(a,48),1));
        choose.setOnClickListener(v->showChoices(a,db,title,kind,false,e,gameKind,hall,false));
        if(gameKind!=null){Button unknown=new Button(a);unknown.setText("未分類");
            unknown.setContentDescription("未分類の機種を一覧から選択");styleButton(unknown);
            row.addView(unknown,new LinearLayout.LayoutParams(dp(a,72),dp(a,44)));
            unknown.setOnClickListener(v->showChoices(a,db,title,kind,false,e,gameKind,hall,true));}
        panel.addView(row);return e;
    }
    static EditText compactNumber(Activity a,LinearLayout panel,String value) {
        LinearLayout row=new LinearLayout(a);row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView caption=new TextView(a);caption.setText("台番号");caption.setTextSize(15);caption.setTextColor(INK);
        row.addView(caption,new LinearLayout.LayoutParams(dp(a,56),-2));
        EditText e=new EditText(a);e.setSingleLine(true);e.setText(value);e.setTextSize(16);
        e.setHint("番号");e.setContentDescription("台番号");machineNumber(e);
        row.addView(e,new LinearLayout.LayoutParams(0,dp(a,48),1));panel.addView(row);return e;
    }
    static EditText compactNumeric(Activity a,LinearLayout row,String title,String value) {
        LinearLayout cell=new LinearLayout(a);cell.setOrientation(LinearLayout.VERTICAL);
        TextView caption=new TextView(a);caption.setText(title);caption.setTextColor(INK);caption.setTextSize(12);
        cell.addView(caption);
        EditText e=new EditText(a);e.setSingleLine(true);e.setTextSize(16);e.setText(value);
        e.setContentDescription(title);numeric(e);cell.addView(e,new LinearLayout.LayoutParams(-1,dp(a,42)));
        row.addView(cell,new LinearLayout.LayoutParams(0,-2,1));return e;
    }
    static long dayTime(String date,EditText time) {
        if(time.getText().toString().isEmpty())throw new IllegalArgumentException("時刻を選択してください");
        return LocalDate.parse(date).atTime(LocalTime.parse(time.getText().toString()))
            .atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
    }
    static final class Moment {
        final EditText date,time;
        Moment(Activity a,LinearLayout panel,String title,Long millis,boolean optional){
            LocalDateTime value=millis==null?null:LocalDateTime.ofInstant(Instant.ofEpochMilli(millis),ZoneId.systemDefault());
            date=FormUi.date(a,panel,title+"日",value==null?"":value.toLocalDate().toString(),optional);
            time=FormUi.time(a,panel,title+"時刻",value==null?"":value.toLocalTime().format(DateTimeFormatter.ofPattern("HH:mm")));
            if(optional){Button clear=new Button(a);clear.setText(title+"を未入力にする");styleButton(clear);panel.addView(clear);clear.setOnClickListener(v->{date.setText("");time.setText("");});}
        }
        Long value() {
            if(date.getText().toString().isEmpty() && time.getText().toString().isEmpty())return null;
            if(date.getText().toString().isEmpty() || time.getText().toString().isEmpty())throw new IllegalArgumentException("日付と時刻を両方選択してください");
            return LocalDateTime.of(LocalDate.parse(date.getText().toString()),LocalTime.parse(time.getText().toString())).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
        }
    }
    static EditText choice(Activity a,LedgerDb db,LinearLayout panel,String title,String value,String kind,boolean filter) {
        return choice(a,db,panel,title,value,kind,filter,null,null);
    }
    static EditText choice(Activity a,LedgerDb db,LinearLayout panel,String title,String value,String kind,boolean filter,
                           java.util.function.Supplier<String> gameKind,java.util.function.Supplier<String> hall) {
        EditText e=field(a,panel,title,value);
        Button choose=new Button(a);choose.setText(title+"を一覧から選択");styleButton(choose);panel.addView(choose);
        choose.setOnClickListener(v->showChoices(a,db,title,kind,filter,e,gameKind,hall,false));
        if(gameKind!=null){
            Button unknown=new Button(a);unknown.setText("未分類の機種を一覧から選択");styleButton(unknown);panel.addView(unknown);
            unknown.setOnClickListener(v->showChoices(a,db,title,kind,false,e,gameKind,hall,true));
        }
        return e;
    }
    private static void showChoices(Activity a,LedgerDb db,String title,String kind,boolean filter,EditText e,
                                    java.util.function.Supplier<String> gameKind,java.util.function.Supplier<String> hall,boolean unclassified){
        try {
            List<String> all=Catalog.names(db,kind,gameKind==null?null:gameKind.get(),hall==null?null:hall.get(),unclassified);
            LinearLayout box=new LinearLayout(a);box.setOrientation(1);box.setPadding(24,8,24,8);
            label(a,box,unclassified?"種別未確認の機種を直近の利用順に表示します。古い候補は名前で検索できます。":"直近の利用順。古い候補は名前で検索できます。");
            EditText search=field(a,box,"名前を検索","");
            ListView list=new ListView(a);box.addView(list,new LinearLayout.LayoutParams(-1,dp(a,280)));
            ArrayAdapter<String> adapter=new ArrayAdapter<>(a,android.R.layout.simple_list_item_1,new ArrayList<>());list.setAdapter(adapter);
            Runnable update=()->{String query=search.getText().toString().trim().toLowerCase(Locale.JAPAN);
                adapter.clear();int shown=0;
                for(String name:all)if(name.toLowerCase(Locale.JAPAN).contains(query)){
                    adapter.add(name);if(++shown>=20)break;
                }
                adapter.notifyDataSetChanged();};update.run();
            AlertDialog d=new AlertDialog.Builder(a).setTitle(title+"を選択").setView(box).setNegativeButton("戻る",null)
                .setNeutralButton(filter?"すべて": "新しい名前を使う",null).create();
            list.setOnItemClickListener((p,item,pos,id)->{e.setText(adapter.getItem(pos));d.dismiss();});
            search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}public void onTextChanged(CharSequence s,int st,int b,int c){update.run();}public void afterTextChanged(Editable x){}});
            d.setOnShowListener(x->d.getButton(DialogInterface.BUTTON_NEUTRAL).setOnClickListener(w->{
                String name=search.getText().toString().trim();
                if(!filter && name.isEmpty()){search.setError("新しい名前を入力してください");return;}
                if(!filter)Catalog.add(db,kind,name);e.setText(filter?"":name);d.dismiss();
            })); d.show();
        }catch(Exception ex){new AlertDialog.Builder(a).setMessage(ex.getMessage()).setPositiveButton("閉じる",null).show();}
    }
}
