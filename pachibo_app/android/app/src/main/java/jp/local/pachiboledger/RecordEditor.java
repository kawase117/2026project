package jp.local.pachiboledger;

import android.app.*;
import android.widget.*;
import android.text.*;
import android.view.View;
import org.json.*;
import java.math.BigInteger;
import java.util.*;

/** Editor for imported and retrospective records, preserving original values and input units. */
final class RecordEditor {
    static void show(Activity a,LedgerDb db,JSONObject existing,Runnable refresh) throws Exception {
        JSONObject row=existing==null?new JSONObject():new JSONObject(existing.toString());
        if(!row.has("id"))row.put("id","local-"+UUID.randomUUID());
        JSONObject details=db.recordDetails(row.getString("id"));
        LinearLayout form=new LinearLayout(a);form.setOrientation(1);form.setPadding(24,12,24,12);ScrollView scroll=new ScrollView(a);scroll.addView(form);
        if(existing!=null){Button counter=new Button(a);counter.setText("小役カウンタを開く");FormUi.styleButton(counter);
            form.addView(counter);counter.setOnClickListener(v->CounterScreen.show(a,db,"record",row.optString("id")));}
        EditText date=FormUi.date(a,form,"遊技日",row.optString("date",java.time.LocalDate.now().toString()),false);
        int timeStart=form.getChildCount();
        EditText start=FormUi.time(a,form,"開始時刻",clock(details,"started_at"));
        EditText end=FormUi.time(a,form,"終了時刻",clock(details,"ended_at"));
        if(!EntryPreferences.time(a))for(int i=timeStart;i<form.getChildCount();i++)form.getChildAt(i).setVisibility(View.GONE);
        Spinner kind=spinner(a,form,"遊技の種類",new String[]{"スロット","パチンコ","その他"},row.optString("kind","スロット"));
        EditText hall=FormUi.choice(a,db,form,"ホール",row.optString("hall"),"hall",false);
        EditText machine=FormUi.choice(a,db,form,"機種",row.optString("machine"),"machine",false,
            ()->{String type=kind.getSelectedItem().toString();return "スロット".equals(type)||"パチンコ".equals(type)?type:null;},
            ()->hall.getText().toString().trim());
        CheckBox expense=new CheckBox(a);expense.setText("遊技に伴う経費として集計");
        expense.setChecked(details.optBoolean("expense","雑費".equals(row.optString("hall"))&&"経費".equals(row.optString("machine"))));
        form.addView(expense);
        LinearLayout expensePanel=new LinearLayout(a);expensePanel.setOrientation(LinearLayout.VERTICAL);form.addView(expensePanel);
        EditText expenseHall=FormUi.choice(a,db,expensePanel,"経費の対象ホール（任意）",details.optString("expense_hall"),"hall",true);
        EditText expenseMachine=FormUi.choice(a,db,expensePanel,"経費の対象機種（任意）",details.optString("expense_machine"),"machine",true,
            ()->null,()->expenseHall.getText().toString().trim());
        expensePanel.setVisibility(expense.isChecked()?View.VISIBLE:View.GONE);
        expense.setOnCheckedChangeListener((button,checked)->expensePanel.setVisibility(checked?View.VISIBLE:View.GONE));
        int numberStart=form.getChildCount();
        EditText number=FormUi.machineNumber(a,form,"台番号",row.optString("machine_number"));
        if(!EntryPreferences.number(a))for(int i=numberStart;i<form.getChildCount();i++)form.getChildAt(i).setVisibility(View.GONE);
        boolean detailed=details.optBoolean("mixed_inputs",false);
        String baseIn=details.optString("unallocated_investment_yen",detailed?"0":Long.toString(row.optLong("investment_yen")));
        String baseOut=details.optString("unallocated_recovery_yen",detailed?"0":Long.toString(row.optLong("recovery_yen")));
        EditText unallocatedIn=null,unallocatedOut=null;
        if(row.has("profit_yen")||!"0".equals(baseIn)||!"0".equals(baseOut)){
            FormUi.label(a,form,"内訳が分からない元データの円換算額。現金投資・回収には数えません。");
            unallocatedIn=FormUi.numeric(a,form,"内訳不明の投資（円換算済み）",baseIn);
            unallocatedOut=FormUi.numeric(a,form,"内訳不明の回収（円換算済み）",baseOut);
        }
        final EditText originalIn=unallocatedIn,originalOut=unallocatedOut;
        EditText investmentCash=FormUi.numeric(a,form,"現金投資（円）",details.optString("investment_cash_input","0"));
        EditText investmentQuantity=FormUi.numeric(a,form,"玉・メダル投資（玉・枚数）",details.optString("investment_quantity_input","0"));
        EditText recoveryCash=FormUi.numeric(a,form,"現金回収（円）",details.optString("recovery_cash_input","0"));
        EditText recoveryQuantity=FormUi.numeric(a,form,"玉・メダル回収（玉・枚数）",details.optString("recovery_quantity_input","0"));
        FormUi.label(a,form,"玉・メダルで入力した分を円に換算します。例：100円に交換する数量が5枚なら「100円＝5枚」。");
        EditText yen=FormUi.numeric(a,form,"交換率：円",details.optString("rate_yen",""));
        EditText units=FormUi.numeric(a,form,"上記の円に交換できる枚数・玉数",details.optString("rate_units",""));
        Runnable hallRate=()->{try{
            if(!yen.getText().toString().isEmpty()||!units.getText().toString().isEmpty())return;
            String selectedHall=hall.getText().toString().trim();
            String unit="パチンコ".equals(kind.getSelectedItem().toString())?"玉":"枚";
            for(JSONObject item:new AccountStore(db).list())if(selectedHall.equals(item.optString("hall"))
                &&unit.equals(item.optString("unit"))&&!item.isNull("rate_yen")){
                yen.setText(item.optString("rate_yen"));units.setText(item.optString("rate_units"));break;
            }
        }catch(Exception ignored){}};
        hall.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}
            public void onTextChanged(CharSequence s,int st,int b,int c){hallRate.run();}public void afterTextChanged(Editable x){}});
        hallRate.run();
        Button account=new Button(a);account.setText("登録した交換率から選ぶ");FormUi.styleButton(account);form.addView(account);
        account.setOnClickListener(v->{try{
            List<JSONObject> accounts=new AccountStore(db).list();String[] names=new String[accounts.size()];
            for(int i=0;i<names.length;i++)names[i]=accounts.get(i).optString("hall")+" / "+accounts.get(i).optString("name");
            new AlertDialog.Builder(a).setTitle("交換率を選択").setItems(names,(d,w)->{JSONObject picked=accounts.get(w);yen.setText(picked.isNull("rate_yen")?"":picked.optString("rate_yen"));units.setText(picked.isNull("rate_units")?"":picked.optString("rate_units"));}).setNegativeButton("戻る",null).show();
        }catch(Exception e){error(a,e);}});
        TextView preview=FormUi.label(a,form,"");
        Runnable calculate=()->{try{
            long in=total(originalIn,investmentCash,investmentQuantity,yen,units),out=total(originalOut,recoveryCash,recoveryQuantity,yen,units);
            BigInteger profit=BigInteger.valueOf(out).subtract(BigInteger.valueOf(in));
            preview.setText(String.format(Locale.JAPAN,"投資 %,d円 / 回収 %,d円",in,out)+"\n収支 "+FormUi.money(profit));FormUi.tint(preview,profit);
        }catch(Exception e){preview.setText("換算するには金額・数量と交換率を入力してください");preview.setTextColor(FormUi.MUTED);}};
        TextWatcher watcher=new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}public void onTextChanged(CharSequence s,int st,int b,int c){calculate.run();}public void afterTextChanged(Editable x){}};
        for(EditText e:new EditText[]{investmentCash,investmentQuantity,recoveryCash,recoveryQuantity,yen,units})e.addTextChangedListener(watcher);
        if(originalIn!=null)originalIn.addTextChangedListener(watcher);
        if(originalOut!=null)originalOut.addTextChangedListener(watcher);
        calculate.run();
        if(!row.optString("duration").isEmpty())FormUi.label(a,form,"以前の時間欄："+row.optString("duration")+"（開始・終了を入力すると遊技時間を計算します）");
        Set<String> tags=new LinkedHashSet<>(TagPicker.ids(row.optJSONArray("tag_ids")));
        TextView tagLabel=FormUi.label(a,form,"タグ："+TagPicker.display(db,TagPicker.array(tags)));
        Button tagButton=new Button(a);tagButton.setText("タグを選択");FormUi.styleButton(tagButton);form.addView(tagButton);
        tagButton.setOnClickListener(v->TagPicker.show(a,db,tags,true,chosen->{tags.clear();tags.addAll(chosen);try{tagLabel.setText("タグ："+TagPicker.display(db,TagPicker.array(tags)));}catch(Exception e){error(a,e);}}));
        EditText memo=FormUi.field(a,form,"メモ（立ち回り・気づいたことなど）",row.optString("memo"));memo.setSingleLine(false);
        int advancedStart=form.getChildCount();
        EditText spins=FormUi.numeric(a,form,"回転数（任意）",details.isNull("spins")?"":details.optString("spins",""));
        EditText work=FormUi.numeric(a,form,"仕事量（円・手入力、任意）",
            "pachinko_formula".equals(details.optString("work_source"))||details.isNull("work_yen")?"":details.optString("work_yen",""));
        PachinkoWorkInput workInput=new PachinkoWorkInput(a,form,details,spins,
            ()->kind.getSelectedItem().toString(),()->{
                try{return new long[]{AmountInput.signed(yen.getText().toString(),false),
                    AmountInput.signed(units.getText().toString(),false)};}
                catch(Exception ignored){return new long[]{0,0};}
            });
        TextWatcher workWatcher=new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int count,int after){}
            public void onTextChanged(CharSequence s,int st,int before,int count){workInput.update();}
            public void afterTextChanged(Editable s){}};
        yen.addTextChangedListener(workWatcher);units.addTextChangedListener(workWatcher);
        kind.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            public void onItemSelected(android.widget.AdapterView<?> p,View v,int position,long id){workInput.update();}
            public void onNothingSelected(android.widget.AdapterView<?> p){}
        });
        if(!EntryPreferences.advanced(a))for(int i=advancedStart;i<form.getChildCount();i++)form.getChildAt(i).setVisibility(View.GONE);
        AlertDialog.Builder builder=new AlertDialog.Builder(a).setTitle(existing==null?"遊技を記録":"遊技の記録を編集").setView(scroll).setPositiveButton("保存",null).setNegativeButton("戻る",null);
        if(row.has("profit_yen"))builder.setNeutralButton("削除",(d,w)->new AlertDialog.Builder(a).setMessage("この記録を削除しますか？").setNegativeButton("戻る",null).setPositiveButton("削除",(x,y)->{db.delete(row.optString("id"));refresh.run();}).show());
        AlertDialog dialog=builder.create();
        dialog.setOnShowListener(v->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(x->{try{
            java.time.LocalDate.parse(date.getText().toString());
            if(hall.getText().toString().trim().isEmpty())throw new IllegalArgumentException("ホールを入力・選択してください");
            long in=total(originalIn,investmentCash,investmentQuantity,yen,units),out=total(originalOut,recoveryCash,recoveryQuantity,yen,units);
            BigInteger profit=BigInteger.valueOf(out).subtract(BigInteger.valueOf(in));
            if(profit.compareTo(BigInteger.valueOf(Long.MIN_VALUE))<0||profit.compareTo(BigInteger.valueOf(Long.MAX_VALUE))>0)
                throw new IllegalArgumentException("収支が大きすぎます");
            Long begin=start.getText().toString().isEmpty()?null:FormUi.dayTime(date.getText().toString(),start);
            Long finish=end.getText().toString().isEmpty()?null:FormUi.dayTime(date.getText().toString(),end);
            if((begin==null)!=(finish==null))throw new IllegalArgumentException("開始と終了を両方入力するか、両方未入力にしてください");
            if(begin!=null&&finish<begin)throw new IllegalArgumentException("終了日時は開始日時以降にしてください");
            row.put("date",date.getText()).put("hall",hall.getText().toString().trim()).put("machine",machine.getText().toString().trim()).put("machine_number",FormUi.numberText(number));
            row.put("kind",kind.getSelectedItem()).put("investment_yen",in).put("recovery_yen",out).put("profit_yen",profit.longValue()).put("tag_ids",TagPicker.array(tags)).put("memo",memo.getText().toString());
            if(begin!=null)row.put("duration",((finish-begin)/60000)+"分");
            details.put("mixed_inputs",true)
                .put("expense",expense.isChecked())
                .put("expense_hall",expense.isChecked()?expenseHall.getText().toString().trim():"")
                .put("expense_machine",expense.isChecked()?expenseMachine.getText().toString().trim():"")
                .put("unallocated_investment_yen",originalIn==null?"0":AmountInput.normalize(originalIn.getText().toString()))
                .put("unallocated_recovery_yen",originalOut==null?"0":AmountInput.normalize(originalOut.getText().toString()))
                .put("investment_cash_input",AmountInput.normalize(investmentCash.getText().toString()))
                .put("investment_quantity_input",AmountInput.normalize(investmentQuantity.getText().toString()))
                .put("recovery_cash_input",AmountInput.normalize(recoveryCash.getText().toString()))
                .put("recovery_quantity_input",AmountInput.normalize(recoveryQuantity.getText().toString()))
                .put("rate_yen",AmountInput.normalize(yen.getText().toString())).put("rate_units",AmountInput.normalize(units.getText().toString()))
                .put("started_at",begin==null?JSONObject.NULL:begin).put("ended_at",finish==null?JSONObject.NULL:finish)
                .put("spins",optionalNumber(spins));
            workInput.save(details,optionalNumber(spins),optionalNumber(work));
            db.saveRecord(row,details);dialog.dismiss();refresh.run();
        }catch(Exception e){error(a,e);}}));dialog.show();
    }
    private static Object optionalNumber(EditText input){
        String text=AmountInput.normalize(input.getText().toString());
        return text.isEmpty()?JSONObject.NULL:AmountInput.signed(text,false);
    }
    private static Spinner spinner(Activity a,LinearLayout form,String title,String[] values,String selected){
        if(!selected.isEmpty()&&!Arrays.asList(values).contains(selected)){
            values=Arrays.copyOf(values,values.length+1);values[values.length-1]=selected;
        }
        FormUi.label(a,form,title);Spinner s=new Spinner(a);s.setContentDescription(title);s.setAdapter(new ArrayAdapter<>(a,android.R.layout.simple_spinner_dropdown_item,values));
        for(int i=0;i<values.length;i++)if(values[i].equals(selected))s.setSelection(i);form.addView(s);return s;
    }
    private static String clock(JSONObject details,String key){
        if(!details.has(key)||details.isNull(key))return "";
        return java.time.Instant.ofEpochMilli(details.optLong(key)).atZone(java.time.ZoneId.systemDefault())
            .toLocalTime().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"));
    }
    private static long mixed(EditText cash,EditText quantity,EditText yen,EditText units){
        long money=AmountInput.signed(cash.getText().toString(),false),count=AmountInput.signed(quantity.getText().toString(),false);
        if(count==0)return money;
        long y=AmountInput.signed(yen.getText().toString(),false),u=AmountInput.signed(units.getText().toString(),false);
        if(y<=0||u<=0)throw new IllegalArgumentException("交換率は0より大きい数で入力してください");
        BigInteger value=BigInteger.valueOf(money).add(new Accounting.Amount(y,u).multiply(count).roundYen());
        if(value.compareTo(BigInteger.valueOf(Long.MAX_VALUE))>0)throw new IllegalArgumentException("換算額が大きすぎます");return value.longValue();
    }
    private static long total(EditText original,EditText cash,EditText quantity,EditText yen,EditText units){
        long base=original==null?0:AmountInput.signed(original.getText().toString(),false);
        try{return Math.addExact(base,mixed(cash,quantity,yen,units));}
        catch(ArithmeticException error){throw new IllegalArgumentException("投資・回収の合計が大きすぎます");}
    }
    private static void error(Activity a,Exception e){new AlertDialog.Builder(a).setMessage(e.getMessage()).setPositiveButton("閉じる",null).show();}
}
