package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.*;
import org.json.JSONObject;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

/** One form for starting, completing and correcting an ordinary one-machine play. */
final class SessionEditor {
    private static final DateTimeFormatter CLOCK=DateTimeFormatter.ofPattern("HH:mm");
    static void show(Activity activity,LedgerDb db,LocalDate date,JSONObject existing,Runnable refresh)throws Exception {
        SessionStore store=new SessionStore(db);
        JSONObject metadata=existing==null?null:existing.getJSONObject("metadata");
        boolean completed=existing!=null&&"ended".equals(existing.getString("state"));
        long[] previous=completed?amounts(store,existing.getString("id")):new long[4];
        LinearLayout form=new LinearLayout(activity);form.setOrientation(1);form.setPadding(16,4,16,4);
        TextView day=FormUi.label(activity,form,"遊技日 "+date);
        day.setPadding(0,2,0,4);
        String startValue=existing==null?LocalTime.now().format(CLOCK):clock(existing.getLong("started_at"));
        EditText start=FormUi.compactTime(activity,form,"開始時刻",startValue,false);
        EditText end=FormUi.compactTime(activity,form,"終了時刻（遊技中は空欄）",completed?clock(existing.getLong("ended_at")):"",!completed);
        boolean showTime=EntryPreferences.time(activity);
        boolean[] timeTouched=new boolean[2];
        start.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}
            public void onTextChanged(CharSequence s,int st,int before,int count){timeTouched[0]=true;}
            public void afterTextChanged(Editable s){}});
        end.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}
            public void onTextChanged(CharSequence s,int st,int before,int count){timeTouched[1]=true;}
            public void afterTextChanged(Editable s){}});
        CheckBox finishWithoutTime=new CheckBox(activity);
        finishWithoutTime.setText("遊技を終了して収支を入力");finishWithoutTime.setChecked(completed);
        if(!showTime){
            ((View)start.getParent()).setVisibility(View.GONE);
            ((View)end.getParent()).setVisibility(View.GONE);
            form.addView(finishWithoutTime);
        }
        Spinner game=new Spinner(activity);game.setContentDescription("遊技種別");
        game.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,new String[]{"スロット","パチンコ"}));
        if(metadata!=null)game.setSelection("パチンコ".equals(metadata.optString("game_kind"))?1:0);
        LinearLayout gameRow=new LinearLayout(activity);gameRow.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView gameLabel=new TextView(activity);gameLabel.setText("種別");gameLabel.setTextColor(FormUi.INK);gameLabel.setTextSize(15);
        gameRow.addView(gameLabel,new LinearLayout.LayoutParams(FormUi.dp(activity,56),-2));
        gameRow.addView(game,new LinearLayout.LayoutParams(0,FormUi.dp(activity,48),1));form.addView(gameRow);
        if(existing!=null)game.setEnabled(false);
        EditText hall=FormUi.compactChoice(activity,db,form,"ホール",metadata==null?"":metadata.optString("hall"),"hall",null,null);
        EditText machine=FormUi.compactChoice(activity,db,form,"機種",metadata==null?"":metadata.optString("machine"),"machine",
            ()->game.getSelectedItem().toString(),()->hall.getText().toString().trim());
        EditText number=FormUi.compactNumber(activity,form,metadata==null?"":metadata.optString("number"));
        if(!EntryPreferences.number(activity))((View)number.getParent()).setVisibility(View.GONE);
        LinearLayout amountsPanel=new LinearLayout(activity);amountsPanel.setOrientation(1);
        TextView amountTitle=FormUi.label(activity,amountsPanel,completed?"収支を訂正":"終了時の投資・回収");
        amountTitle.setPadding(0,6,0,2);
        LinearLayout inputs=new LinearLayout(activity);
        EditText cashIn=FormUi.compactNumeric(activity,inputs,"現金投資（円）",Long.toString(previous[0]));
        EditText quantityIn=FormUi.compactNumeric(activity,inputs,"貯玉・貯メダル投資（玉・枚）",Long.toString(previous[1]));
        amountsPanel.addView(inputs);
        LinearLayout outputs=new LinearLayout(activity);
        EditText cashOut=FormUi.compactNumeric(activity,outputs,"現金回収（円）",Long.toString(previous[2]));
        EditText quantityOut=FormUi.compactNumeric(activity,outputs,"玉・メダル回収（玉・枚）",Long.toString(previous[3]));
        amountsPanel.addView(outputs);
        TextView rate=FormUi.label(activity,amountsPanel,"");rate.setPadding(0,4,0,4);
        form.addView(amountsPanel);
        Runnable updateAmounts=()->amountsPanel.setVisibility((showTime?
            end.getText().toString().trim().isEmpty():!finishWithoutTime.isChecked())?View.GONE:View.VISIBLE);
        end.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}
            public void onTextChanged(CharSequence s,int st,int before,int count){updateAmounts.run();}
            public void afterTextChanged(Editable s){}});updateAmounts.run();
        finishWithoutTime.setOnCheckedChangeListener((button,checked)->updateAmounts.run());
        Runnable updateRate=()->{
            try {
                String selectedHall=hall.getText().toString().trim();
                JSONObject account=null;
                for(JSONObject row:new AccountStore(db).list())if(selectedHall.equals(row.optString("hall"))
                    && ("パチンコ".equals(game.getSelectedItem().toString())?"玉":"枚").equals(row.optString("unit"))
                    && !row.isNull("rate_yen")){account=row;break;}
                rate.setText(account==null?"交換率：未登録（玉・メダル入力にはホール設定が必要）":
                    "交換率："+account.getLong("rate_yen")+"円 / "+account.getLong("rate_units")+account.optString("unit"));
            }catch(Exception error){rate.setText("交換率：確認できません");}
        };
        hall.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}
            public void onTextChanged(CharSequence s,int st,int before,int count){updateRate.run();}
            public void afterTextChanged(Editable s) {}});
        game.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            public void onItemSelected(android.widget.AdapterView<?> p,android.view.View v,int pos,long row){updateRate.run();}
            public void onNothingSelected(android.widget.AdapterView<?> p){}
        });updateRate.run();
        Set<String> tags=new LinkedHashSet<>(metadata==null?Collections.emptySet():TagPicker.ids(metadata.optJSONArray("tag_ids")));
        Button optional=new Button(activity);optional.setText("タグ・メモ（任意）");FormUi.styleButton(optional);form.addView(optional);
        LinearLayout optionalPanel=new LinearLayout(activity);optionalPanel.setOrientation(1);form.addView(optionalPanel);
        TextView tagLabel=FormUi.label(activity,optionalPanel,"タグ："+TagPicker.display(db,TagPicker.array(tags)));
        Button chooseTags=new Button(activity);chooseTags.setText("タグを選択（任意）");FormUi.styleButton(chooseTags);optionalPanel.addView(chooseTags);
        chooseTags.setOnClickListener(v->TagPicker.show(activity,db,tags,true,chosen->{
            tags.clear();tags.addAll(chosen);
            try{tagLabel.setText("タグ："+TagPicker.display(db,TagPicker.array(tags)));}catch(Exception error){showError(activity,error);}
        }));
        EditText memo=FormUi.field(activity,optionalPanel,"メモ（任意）",metadata==null?"":metadata.optString("memo"));memo.setSingleLine(false);
        LinearLayout advanced=new LinearLayout(activity);advanced.setOrientation(1);
        EditText spins=FormUi.numeric(activity,advanced,"回転数（任意）",optionalText(metadata,"spins"));
        EditText work=FormUi.numeric(activity,advanced,"仕事量（円・手入力、任意）",
            metadata!=null&&"pachinko_formula".equals(metadata.optString("work_source"))?"":optionalText(metadata,"work_yen"));
        PachinkoWorkInput workInput=new PachinkoWorkInput(activity,advanced,metadata,spins,
            ()->game.getSelectedItem().toString(),()->{
                try{
                    String selectedHall=hall.getText().toString().trim();
                    if(metadata!=null&&selectedHall.equals(metadata.optString("hall"))
                        &&"pachinko_formula".equals(metadata.optString("work_source"))
                        &&!metadata.isNull("work_exchange_yen")&&!metadata.isNull("work_exchange_balls"))
                        return new long[]{metadata.optLong("work_exchange_yen"),metadata.optLong("work_exchange_balls")};
                    String unit="パチンコ".equals(game.getSelectedItem().toString())?"玉":"枚";
                    for(JSONObject selected:new AccountStore(db).list())
                        if(selectedHall.equals(selected.optString("hall"))&&unit.equals(selected.optString("unit"))
                            &&!selected.isNull("rate_yen"))
                            return new long[]{selected.optLong("rate_yen"),selected.optLong("rate_units")};
                    return new long[]{0,0};
                }catch(Exception ignored){return new long[]{0,0};}
            });
        game.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            public void onItemSelected(android.widget.AdapterView<?> p,View v,int pos,long row){updateRate.run();workInput.update();}
            public void onNothingSelected(android.widget.AdapterView<?> p){}
        });
        hall.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}
            public void onTextChanged(CharSequence s,int st,int before,int count){workInput.update();}
            public void afterTextChanged(Editable s){}});
        optionalPanel.addView(advanced);
        advanced.setVisibility(EntryPreferences.advanced(activity)?View.VISIBLE:View.GONE);
        optionalPanel.setVisibility(tags.isEmpty()&&memo.getText().length()==0&&!EntryPreferences.advanced(activity)?View.GONE:View.VISIBLE);
        optional.setOnClickListener(v->optionalPanel.setVisibility(optionalPanel.getVisibility()==android.view.View.VISIBLE?
            android.view.View.GONE:android.view.View.VISIBLE));
        ScrollView scroll=new ScrollView(activity);scroll.addView(form);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle(existing==null?"遊技を記録":completed?"遊技記録を編集":"遊技を終了・記録")
            .setView(scroll).setNeutralButton("保存",null).setNegativeButton("戻る",null).create();
        dialog.setOnShowListener(v->dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(button->{
            try {
                String selectedHall=hall.getText().toString().trim(),selectedMachine=machine.getText().toString().trim();
                if(selectedHall.isEmpty()||selectedMachine.isEmpty())throw new IllegalArgumentException("ホールと機種を選択してください");
                String kind=game.getSelectedItem().toString();
                long started=showTime?FormUi.dayTime(date.toString(),start):existing!=null?
                    existing.getLong("started_at"):automaticTime(date);
                String endText=showTime?end.getText().toString().trim():finishWithoutTime.isChecked()?"automatic":"";
                long ci=amount(cashIn),qi=amount(quantityIn),co=amount(cashOut),qo=amount(quantityOut);
                if(endText.isEmpty()&&(ci!=0||qi!=0||co!=0||qo!=0))
                    throw new IllegalArgumentException("投資・回収を入力した場合は終了時刻も入力してください");
                if(completed&&endText.isEmpty())throw new IllegalArgumentException("終了済みの記録には終了時刻が必要です");
                Long ended=endText.isEmpty()?null:showTime?FormUi.dayTime(date.toString(),end):
                    completed?existing.getLong("ended_at"):Math.max(started,automaticTime(date));
                if(ended!=null&&ended<started)throw new IllegalArgumentException("終了時刻は開始時刻以降にしてください");
                boolean timeRecorded=showTime&&(metadata==null||metadata.optBoolean("time_recorded",true)
                    ||timeTouched[0]&&timeTouched[1]);
                if(!showTime&&completed)timeRecorded=metadata.optBoolean("time_recorded",true);
                Object spinsValue=optionalNumber(spins),workValue=optionalNumber(work);
                JSONObject workFields=new JSONObject();workInput.save(workFields,spinsValue,workValue);
                AccountStore accounts=new AccountStore(db);
                JSONObject account=accounts.forHall(selectedHall,kind);
                Long yen=account.isNull("rate_yen")?null:account.getLong("rate_yen");
                Long units=account.isNull("rate_units")?null:account.getLong("rate_units");
                if((qi>0||qo>0)&&yen==null&&!completed)throw new IllegalArgumentException("ホールの交換率を先に登録してください");
                String machineNumber=FormUi.numberText(number),note=memo.getText().toString();
                if(existing==null){
                    String newId=UUID.randomUUID().toString();
                    JSONObject meta=AccountStore.snapshot(account,new JSONObject().put("machine",selectedMachine)
                        .put("number",machineNumber).put("game_kind",kind).put("tag_ids",TagPicker.array(tags)).put("memo",note)
                        .put("time_recorded",timeRecorded).put("spins",spinsValue));
                    for(Iterator<String> keys=workFields.keys();keys.hasNext();){String key=keys.next();meta.put(key,workFields.get(key));}
                    store.startAt(newId,date.toString(),account.getString("id"),meta,started);
                    if(ended!=null)store.finishWithAmountsAt(newId,UUID.randomUUID().toString(),ci,qi,co,qo,yen,units,note,TagPicker.array(tags),ended);
                }else if(completed){
                    store.reviseCompleted(existing.getString("id"),metadata,account,selectedHall,selectedMachine,machineNumber,
                        note,TagPicker.array(tags),started,ended,ci,qi,co,qo,yen,units);
                }else if(ended==null){
                    store.updateActiveEdited(existing.getString("id"),metadata,account,selectedHall,selectedMachine,
                        machineNumber,note,TagPicker.array(tags),started);
                }else{
                    store.completeEdited(existing.getString("id"),metadata,account,selectedHall,selectedMachine,machineNumber,kind,note,
                        TagPicker.array(tags),started,ended,UUID.randomUUID().toString(),ci,qi,co,qo,yen,units);
                }
                if(existing!=null){JSONObject patch=new JSONObject().put("time_recorded",timeRecorded).put("spins",spinsValue);
                    for(Iterator<String> keys=workFields.keys();keys.hasNext();){String key=keys.next();patch.put(key,workFields.get(key));}
                    store.patchMetadata(existing.getString("id"),patch);
                }
                Catalog.add(db,"hall",selectedHall);Catalog.add(db,"machine",selectedMachine);
                dialog.dismiss();refresh.run();
            }catch(Exception error){showError(activity,error);}
        }));dialog.show();
    }
    private static long amount(EditText input){return AmountInput.signed(input.getText().toString(),false);}
    private static Object optionalNumber(EditText input){
        String value=AmountInput.normalize(input.getText().toString());
        return value.isEmpty()?JSONObject.NULL:AmountInput.signed(value,false);
    }
    private static String optionalText(JSONObject metadata,String key){
        return metadata==null||metadata.isNull(key)?"":metadata.optString(key,"");
    }
    private static long automaticTime(LocalDate date){
        return (date.equals(LocalDate.now())?java.time.LocalDateTime.now():date.atStartOfDay())
            .atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
    }
    private static long[] amounts(SessionStore store,String id)throws Exception {
        long[] result=new long[4];
        for(JSONObject row:store.details(id,false)){
            long delta=row.getLong("delta");int index=("cash".equals(row.getString("kind"))?0:1)+(delta<0?0:2);
            result[index]=Math.addExact(result[index],delta<0?Math.negateExact(delta):delta);
        }
        return result;
    }
    private static String clock(long millis){return java.time.Instant.ofEpochMilli(millis)
        .atZone(java.time.ZoneId.systemDefault()).toLocalTime().format(CLOCK);}
    private static void showError(Activity a,Exception error){new AlertDialog.Builder(a).setTitle("入力を確認してください")
        .setMessage(error.getMessage()).setPositiveButton("閉じる",null).show();}
}
