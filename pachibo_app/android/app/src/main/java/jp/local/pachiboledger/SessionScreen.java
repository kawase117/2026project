package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DatePickerDialog;
import android.text.Editable;
import android.text.TextWatcher;
import android.widget.*;
import org.json.JSONObject;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.*;

final class SessionScreen {
    private final Activity activity;
    private final SessionStore store;
    private final LedgerDb db;
    private final Runnable refresh;
    SessionScreen(Activity activity, LedgerDb db, Runnable refresh) {
        this.activity = activity; this.db=db; store = new SessionStore(db); this.refresh = refresh;
    }
    interface Action { void run() throws Exception; }
    private void attempt(Action action) {
        try { action.run(); } catch (Exception e) {
            new AlertDialog.Builder(activity).setTitle("入力を確認してください").setMessage(e.getMessage()).setPositiveButton("閉じる", null).show();
        }
    }
    private void label(LinearLayout panel, String value) {
        TextView text = new TextView(activity); text.setText(value); text.setTextSize(17); text.setPadding(12,12,12,12); panel.addView(text);
    }
    private void button(LinearLayout panel, String title, Action action) {
        Button button = new Button(activity); FormUi.styleButton(button); button.setText(title); button.setOnClickListener(v -> attempt(action)); panel.addView(button);
    }
    private EditText field(LinearLayout panel, String title, String value) {
        if(title.equals("ホール"))return FormUi.choice(activity,db,panel,title,value,"hall",false);
        if(title.startsWith("機種") || title.equals("次の機種"))return FormUi.choice(activity,db,panel,title,value,"machine",false);
        EditText e=FormUi.field(activity,panel,title,value);
        if(title.contains("円") || title.contains("玉・枚") || title.contains("玉・メダル") || title.startsWith("数量") || title.startsWith("移動数量") || title.contains("貯玉に戻した数量"))FormUi.numeric(e);
        return e;
    }
    private LinearLayout form() { LinearLayout form = new LinearLayout(activity); form.setOrientation(1); form.setPadding(24,12,24,12); return form; }
    private void dialog(String title, LinearLayout form, Action save) {
        ScrollView scroll = new ScrollView(activity); scroll.addView(form);
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle(title).setView(scroll)
            .setPositiveButton("保存", null).setNegativeButton("戻る", null).create();
        dialog.setOnShowListener(v -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(b -> attempt(() -> {
            save.run(); dialog.dismiss(); refresh.run();
        })));
        dialog.show();
    }
    private static String id() { return UUID.randomUUID().toString(); }
    private static long number(EditText input) {
        String text = input.getText().toString().trim();
        if (text.isEmpty()) throw new IllegalArgumentException("数量・金額を入力してください（ゼロの場合は0）");
        return AmountInput.signed(text,false);
    }
    private static Long optional(EditText input) { return input.getText().toString().trim().isEmpty() ? null : number(input); }
    private static Set<String> selection(String id) { return Collections.singleton(id); }
    private String result(String id) {
        Accounting.Result result = store.calculate(selection(id));
        if(!result.hasObservations)return "投資・回収は遊技完了時に入力";
        return "玉・メダル込みの収支 " + (result.evaluated == null ? "計算待ち" : result.evaluated.roundYen() + "円") + " ／ 現金収支 " + result.cash + "円";
    }
    void render(LinearLayout panel) {
        attempt(() -> {
            button(panel,"ホール・交換率を登録",this::accounts);
            label(panel,"記録一覧。遊技の開始はカレンダーから行います。タップして編集・削除できます。");
        });
    }
    void recordActions(JSONObject row) {
        try {
            String sessionId=row.getString("id");boolean active="active".equals(row.optString("state"));
            new AlertDialog.Builder(activity).setTitle("記録の操作")
                .setItems(active?new String[]{"開いて入力","削除"}:new String[]{"開いて編集","収支明細を訂正","削除"},
                    (dialog,which)->{
                        if(active){if(which==0)attempt(()->SessionEditor.show(activity,db,LocalDate.parse(row.getString("date")),store.session(sessionId),refresh));
                            else confirmDelete(sessionId);}
                        else if(which==0)attempt(()->SessionEditor.show(activity,db,LocalDate.parse(row.getString("date")),store.session(sessionId),refresh));
                        else if(which==1)attempt(()->details(sessionId));
                        else confirmDelete(sessionId);
                    }).show();
        }catch(Exception error){new AlertDialog.Builder(activity).setMessage(error.getMessage()).setPositiveButton("閉じる",null).show();}
    }
    void confirmDelete(String sessionId) {
        new AlertDialog.Builder(activity).setTitle("記録を削除")
            .setMessage("この台の記録と投資・回収明細を削除します。元に戻せません。")
            .setNegativeButton("戻る",null).setPositiveButton("削除",(dialog,which)->attempt(()->{
                store.deleteSession(sessionId);refresh.run();
            })).show();
    }
    private void editTags(String sessionId,JSONObject metadata) {
        TagPicker.show(activity,db,TagPicker.ids(metadata.optJSONArray("tag_ids")),true,chosen->attempt(()->{
            store.patchMetadata(sessionId,new JSONObject().put("tag_ids",TagPicker.array(chosen))); refresh.run();
        }));
    }

    void details(String sessionId) throws Exception {
        LinearLayout panel=form();
        label(panel,result(sessionId));
        JSONObject timing=store.session(sessionId);java.text.SimpleDateFormat timeFormat=new java.text.SimpleDateFormat("M/d HH:mm",Locale.JAPAN);
        label(panel,"開始 "+timeFormat.format(new Date(timing.getLong("started_at")))+(timing.isNull("ended_at")?" ／ 遊技中":"\n終了 "+timeFormat.format(new Date(timing.getLong("ended_at")))+" ／ 遊技時間 "+((timing.getLong("ended_at")-timing.getLong("started_at"))/60000)+"分"));
        label(panel,"明細をタップすると訂正できます。履歴から各明細の最新の変更を元に戻せます。");
        ScrollView scroll=new ScrollView(activity); scroll.addView(panel);
        AlertDialog list=new AlertDialog.Builder(activity).setTitle("投資・回収・台移動の明細")
            .setView(scroll).setPositiveButton("閉じる",null).create();
        button(panel,"ホール・機種・台番号・メモを編集",()->{ list.dismiss(); editBasics(sessionId); });
        int count=0;
        for(boolean transfer:new boolean[]{false,true}) for(JSONObject row:store.details(sessionId,transfer)) {
            count++;
            String title;
            if(transfer) title=(sessionId.equals(row.getString("from_id")) ? "次の台へ持出" : "前の台から持込")
                +"："+(row.isNull("quantity") ? "数量不明" : row.getLong("quantity")+" 玉・枚");
            else title=("cash".equals(row.getString("kind")) ? (row.getLong("delta")<0 ? "現金投資" : "現金回収")
                : (row.getLong("delta")<0 ? "玉・メダル投資" : "玉・メダル回収"))
                +"："+java.math.BigInteger.valueOf(row.getLong("delta")).abs()+("cash".equals(row.getString("kind")) ? " 円" : " 玉・枚");
            if(transfer || !"cash".equals(row.optString("kind"))) title+="\n交換率："+
                (row.isNull("rate_yen") ? "未設定" : row.getLong("rate_yen")+"円 / "+row.getLong("rate_units")+"玉・枚");
            button(panel,title,()->{ list.dismiss(); correct(row,transfer); });
        }
        if(count==0) label(panel,"まだ明細がありません。");
        button(panel,"訂正履歴・元に戻す",()->{ list.dismiss(); history(sessionId); });
        list.show();
    }

    private static String historyValue(JSONObject row,boolean transfer) throws Exception {
        String key=transfer ? "quantity" : "delta";
        String value=row.isNull(key) ? "不明" : row.getString(key);
        value+=!transfer && "cash".equals(row.optString("kind")) ? "円" : "玉・枚";
        if(transfer || !"cash".equals(row.optString("kind"))) value+=" / 交換率 "+
            (row.isNull("rate_yen") ? "未設定" : row.getString("rate_yen")+"円："+row.getString("rate_units")+"玉・枚");
        return value;
    }

    private void history(String sessionId) throws Exception {
        LinearLayout panel=form(); ScrollView scroll=new ScrollView(activity); scroll.addView(panel);
        AlertDialog list=new AlertDialog.Builder(activity).setTitle("訂正履歴").setView(scroll).setPositiveButton("閉じる",null).create();
        label(panel,"各明細の最新の変更を戻せます。元に戻した操作も履歴に残ります。この機能の追加前の訂正履歴はありません。");
        List<JSONObject> edits=store.history(sessionId);
        if(edits.isEmpty()) label(panel,"訂正履歴はありません。");
        Set<String> seen=new HashSet<>();
        for(JSONObject edit:edits) {
            boolean transfer="transfers".equals(edit.getString("entity_type"));
            JSONObject before=new JSONObject(edit.getString("before_json")),after=new JSONObject(edit.getString("after_json"));
            String entity=edit.getString("entity_type")+":"+edit.getString("entity_id");
            String title=new java.text.SimpleDateFormat("yyyy/MM/dd HH:mm:ss",Locale.JAPAN).format(new Date(edit.getLong("created_at")))
                + (edit.isNull("reverted_edit_id") ? " 訂正" : " 元に戻す")
                + (transfer ? "（台移動）" : "")+"\n"+historyValue(before,transfer)+"\n→ "+historyValue(after,transfer);
            label(panel,title);
            // Revision, rather than clock time, determines which entry is safe to undo.
            boolean latest=true;
            for(JSONObject other:edits) if(edit.getString("entity_type").equals(other.getString("entity_type"))
                && edit.getString("entity_id").equals(other.getString("entity_id")) && other.getLong("revision")>edit.getLong("revision")) latest=false;
            if(latest && seen.add(entity)) button(panel,"この変更を元に戻す",()->{
                new AlertDialog.Builder(activity).setTitle("変更を元に戻す")
                    .setMessage(historyValue(after,transfer)+"\n↓\n"+historyValue(before,transfer)+(transfer ? "\n移動元・移動先の両方に反映します。" : ""))
                    .setNegativeButton("戻る",null).setPositiveButton("元に戻す",(d,w)->attempt(()->{
                        store.undo(edit.getString("id")); list.dismiss(); refresh.run(); history(sessionId);
                    })).show();
            });
        }
        list.show();
    }

    private void correct(JSONObject row,boolean transfer) throws Exception {
        LinearLayout panel=form();
        boolean cash=!transfer && "cash".equals(row.getString("kind"));
        String column=transfer ? "quantity" : "delta";
        label(panel,transfer ? "移動元・移動先の両方に反映されます。両台を合わせた収支は変わりません。"
            : "投資・回収の区分を選び、金額・数量を入力してください。");
        RadioGroup direction=new RadioGroup(activity);
        if(!transfer) {
            RadioButton expense=new RadioButton(activity); expense.setId(1); expense.setText(cash ? "投資" : "再プレイ（口座から使用）");
            RadioButton income=new RadioButton(activity); income.setId(2); income.setText(cash ? "回収" : "玉・メダル回収");
            direction.addView(expense); direction.addView(income); panel.addView(direction);
            direction.check(row.getLong("delta")<0 ? 1 : 2);
        }
        EditText amount=field(panel,transfer ? "移動数量（不明なら空欄）" : cash ? "金額（円）" : "数量（玉・枚）",
            row.isNull(column) ? "" : java.math.BigInteger.valueOf(row.getLong(column)).abs().toString());
        
        EditText yen=cash ? null : field(panel,"交換率：円（例：100円）",row.isNull("rate_yen") ? "" : row.getString("rate_yen"));
        EditText units=cash ? null : field(panel,"上記の円に交換できる玉・枚",row.isNull("rate_units") ? "" : row.getString("rate_units"));
        if(!cash)FormUi.conversion(activity,panel,amount,yen,units);
        dialog("明細を訂正",panel,()->store.correct(row,transfer,
            transfer ? optional(amount) : AmountInput.signed(amount.getText().toString(),direction.getCheckedRadioButtonId()==1),
            cash ? null : optional(yen),cash ? null : optional(units)));
    }
    private void start() throws Exception {
        LocalDate today=LocalDate.now();
        new DatePickerDialog(activity,(picker,year,month,day)->attempt(()->startOnDate(LocalDate.of(year,month+1,day))),
            today.getYear(),today.getMonthValue()-1,today.getDayOfMonth()).show();
    }

    void startOnDate(LocalDate date) throws Exception {
        LinearLayout form = form();
        label(form,"遊技日："+date+"（開始・終了はこの日の時刻）");
        EditText begun=FormUi.time(activity,form,"開始時刻",LocalTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm")));
        label(form,"終了時刻：遊技完了時に入力");
        Spinner game=new Spinner(activity);game.setContentDescription("遊技種別");
        game.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,new String[]{"スロット","パチンコ"}));
        FormUi.label(activity,form,"遊技種別");form.addView(game);
        EditText hall=FormUi.choice(activity,db,form,"ホール","","hall",false);
        EditText machine=FormUi.choice(activity,db,form,"機種","","machine",false,
            ()->game.getSelectedItem().toString(),()->hall.getText().toString().trim());
        final String[] previousGame={game.getSelectedItem().toString()};
        game.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
            public void onItemSelected(android.widget.AdapterView<?> parent,android.view.View view,int position,long selectedId){
                String selected=game.getSelectedItem().toString();
                if(!selected.equals(previousGame[0])){machine.setText("");previousGame[0]=selected;}
            }
            public void onNothingSelected(android.widget.AdapterView<?> parent){}
        });
        EditText number=FormUi.machineNumber(activity,form,"台番号","");
        Set<String> tags=new LinkedHashSet<>();
        TextView tagLabel=FormUi.label(activity,form,"タグ：未設定");
        button(form,"タグを選択（任意）",()->TagPicker.show(activity,db,tags,true,selected->{
            tags.clear();tags.addAll(selected);attempt(()->tagLabel.setText("タグ："+TagPicker.display(db,TagPicker.array(tags))));
        }));
        String sessionId = id();
        dialog("遊技を開始", form, () -> {
            String selectedHall=hall.getText().toString().trim(),selectedMachine=machine.getText().toString().trim();
            if(selectedHall.isEmpty()||selectedMachine.isEmpty())throw new IllegalArgumentException("ホールと機種を選択してください");
            long start=FormUi.dayTime(date.toString(),begun);
            String gameKind=game.getSelectedItem().toString();
            JSONObject account=new AccountStore(db).forHall(selectedHall,gameKind);
            JSONObject metadata=AccountStore.snapshot(account,new JSONObject().put("machine",selectedMachine)
                .put("number",FormUi.numberText(number)).put("game_kind",gameKind).put("tag_ids",TagPicker.array(tags)).put("memo",""));
            store.startAt(sessionId,date.toString(),account.getString("id"),metadata,start);
            Catalog.add(db,"hall",selectedHall);Catalog.add(db,"machine",selectedMachine);
        });
    }
    private void add(String sessionId, boolean cash) throws Exception {
        JSONObject defaults=store.metadata(sessionId);
        LinearLayout form = form(); String operation = id();
        EditText amount = field(form, cash ? "今回追加する現金（円）" : "今回の口座減少（玉・枚、手数料込み）", "");
        
        EditText yen = cash ? null : field(form, "交換率：円（例：100円）",defaultValue(defaults,"default_rate_yen"));
        EditText units = cash ? null : field(form, "上記の円に交換できる玉・枚",defaultValue(defaults,"default_rate_units"));
        if(!cash)FormUi.conversion(activity,form,amount,yen,units);
        dialog(cash ? "現金追加" : "再プレイ追加", form, () -> store.add(operation, sessionId, cash, -number(amount), cash ? null : optional(yen), cash ? null : optional(units)));
    }
    void finish(String sessionId) throws Exception {
        JSONObject session=store.session(sessionId),defaults=session.getJSONObject("metadata");
        LinearLayout form = form(); String operation = id();
        label(form,"遊技日："+session.getString("date"));
        label(form,"開始時刻："+new java.text.SimpleDateFormat("HH:mm",Locale.JAPAN).format(new Date(session.getLong("started_at"))));
        EditText ended=FormUi.time(activity,form,"終了時刻",LocalTime.now().format(java.time.format.DateTimeFormatter.ofPattern("HH:mm")));
        label(form,defaults.optString("hall")+" ／ "+defaults.optString("machine"));
        label(form,"途中で記録した投資は再入力しないでください。現金に交換した分は現金回収だけに入力します。");
        EditText cashIn=FormUi.numeric(activity,form,"現金投資（円）","0");
        EditText quantityIn=FormUi.numeric(activity,form,"玉・メダル投資（再プレイの玉・枚数）","0");
        EditText cashOut=FormUi.numeric(activity,form,"現金回収（円）","0");
        EditText quantityOut=FormUi.numeric(activity,form,"玉・メダル回収（貯玉の玉・枚数）","0");
        Long storedYen=defaults.isNull("default_rate_yen")?null:defaults.getLong("default_rate_yen");
        Long storedUnits=defaults.isNull("default_rate_units")?null:defaults.getLong("default_rate_units");
        if(storedYen==null){
            JSONObject current=new AccountStore(db).forHall(defaults.optString("hall"),defaults.optString("game_kind","スロット"));
            if(!current.isNull("rate_yen")){storedYen=current.getLong("rate_yen");storedUnits=current.getLong("rate_units");}
        }
        final Long yen=storedYen,units=storedUnits;
        label(form,"交換率："+(yen==null?"未登録（玉・メダル入力にはホール設定が必要）":yen+"円 / "+units+defaults.optString("unit")));
        TextView preview=FormUi.label(activity,form,"");
        Runnable calculate=()->{try{
            long ci=number(cashIn),qi=number(quantityIn),co=number(cashOut),qo=number(quantityOut);
            Accounting.Result previous=store.calculate(selection(sessionId));
            if(previous.hasObservations&&previous.evaluated==null)throw new IllegalArgumentException("以前の明細の交換率が未設定です");
            Accounting.Amount projected=(previous.hasObservations?previous.evaluated:new Accounting.Amount(0,1))
                .add(new Accounting.Amount(co-ci,1));
            if(qi>0||qo>0){if(yen==null||units==null)throw new IllegalArgumentException("ホールの交換率が未登録です");
                projected=projected.add(new Accounting.Amount(yen,units).multiply(qo-qi));}
            java.math.BigInteger total=projected.roundYen();
            preview.setText("保存後の収支："+FormUi.money(total));FormUi.tint(preview,total);
        }catch(Exception e){preview.setText("金額・数量と交換率を確認すると収支を表示します");preview.setTextColor(FormUi.MUTED);}};
        TextWatcher amounts=new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int af){}public void onTextChanged(CharSequence s,int st,int b,int c){calculate.run();}public void afterTextChanged(Editable s){}};
        for(EditText entry:new EditText[]{cashIn,quantityIn,cashOut,quantityOut})entry.addTextChangedListener(amounts);
        calculate.run();
        Set<String> tags=new LinkedHashSet<>(TagPicker.ids(defaults.optJSONArray("tag_ids")));
        TextView tagLabel=FormUi.label(activity,form,"タグ："+TagPicker.display(db,TagPicker.array(tags)));
        button(form,"タグを選択（任意）",()->TagPicker.show(activity,db,tags,true,selected->{
            tags.clear();tags.addAll(selected);attempt(()->tagLabel.setText("タグ："+TagPicker.display(db,TagPicker.array(tags))));
        }));
        EditText memo=FormUi.field(activity,form,"メモ（分析に役立つ状況や判断）",defaults.optString("memo"));memo.setSingleLine(false);
        dialog("遊技完了・収支を入力", form, () -> store.finishWithAmountsAt(sessionId,operation,number(cashIn),number(quantityIn),
            number(cashOut),number(quantityOut),yen,units,memo.getText().toString(),TagPicker.array(tags),
            FormUi.dayTime(session.getString("date"),ended)));
    }
    private void move(String sessionId) throws Exception {
        JSONObject original = null;
        for (JSONObject row : store.sessions()) if (sessionId.equals(row.getString("id"))) original = row.getJSONObject("metadata");
        if (original == null) throw new IllegalArgumentException("記録がありません");
        JSONObject metadata = new JSONObject(original.toString());
        LinearLayout form = form(); String next = id(), transfer = id();
        EditText quantity = field(form, "次の台へ持っていく玉・枚（不明なら空欄）", "");
        
        EditText yen = field(form, "交換率：円（例：100円）",defaultValue(metadata,"default_rate_yen"));
        EditText units = field(form, "上記の円に交換できる玉・枚",defaultValue(metadata,"default_rate_units"));
        FormUi.conversion(activity,form,quantity,yen,units);
        EditText machine = FormUi.choice(activity,db,form,"次の機種","","machine",false,
            ()->metadata.optString("game_kind","スロット"),()->metadata.optString("hall"));
        EditText number = FormUi.machineNumber(activity,form,"次の台番号","");
        label(form, "同じ口座・レートでの移動です。保存すると現在の台を終了します。");
        FormUi.Moment moved=new FormUi.Moment(activity,form,"移動",System.currentTimeMillis(),false);
        dialog("次の台へ", form, () -> {
            metadata.put("machine", machine.getText()).put("number", FormUi.numberText(number)).put("memo", "");
            store.moveAt(sessionId, next, transfer, optional(quantity), optional(yen), optional(units), metadata,moved.value());
        });
    }

    private static String defaultValue(JSONObject row,String key) { return row.isNull(key) ? "" : row.optString(key,""); }
    private static String accountLabel(JSONObject row) {
        return row.optString("hall")+" ／ "+row.optString("name")+"（"+row.optString("unit")+"）\n交換率："+
            (row.isNull("rate_yen") ? "未設定" : row.optString("rate_yen")+"円 / "+row.optString("rate_units")+row.optString("unit"));
    }
    private void accounts() throws Exception {
        LinearLayout panel=form(); ScrollView scroll=new ScrollView(activity); scroll.addView(panel);
        AlertDialog list=new AlertDialog.Builder(activity).setTitle("ホールの交換率").setView(scroll).setPositiveButton("閉じる",null).create();
        label(panel,"ホールごとにスロット・パチンコの交換率を登録します。例：100円に交換する数量が5枚なら「100円＝5枚」。");
        button(panel,"ホールの交換率を登録",()->{ list.dismiss(); editAccount(null); });
        for(JSONObject account:new AccountStore(db).list()) button(panel,accountLabel(account),()->{ list.dismiss(); editAccount(account); });
        list.show();
    }
    private void editAccount(JSONObject existing) {
        LinearLayout panel=form();
        label(panel,"登録した条件は次に開始する遊技で使います。変更しても開始済みの記録や収支は変わりません。");
        EditText hall=field(panel,"ホール",existing==null ? "" : existing.optString("hall"));
        RadioGroup unit=new RadioGroup(activity);
        RadioButton medals=new RadioButton(activity); medals.setId(1); medals.setText("枚（スロット）");
        RadioButton balls=new RadioButton(activity); balls.setId(2); balls.setText("玉（パチンコ）");
        unit.addView(medals); unit.addView(balls); unit.check(existing!=null && "玉".equals(existing.optString("unit")) ? 2 : 1); panel.addView(unit);
        EditText yen=field(panel,"交換率：円（例：100円）",existing==null ? "" : defaultValue(existing,"rate_yen"));
        EditText units=field(panel,"上記の円に交換できる玉・枚",existing==null ? "" : defaultValue(existing,"rate_units"));
        
        String accountId=existing==null ? "account-"+id() : existing.optString("id");
        dialog(existing==null ? "ホールの交換率を登録" : "ホールの交換率を編集",panel,()->{
            String gameKind=unit.getCheckedRadioButtonId()==1?"スロット":"パチンコ";
            new AccountStore(db).save(accountId,existing,hall.getText().toString(),existing==null?gameKind:existing.optString("name"),
                unit.getCheckedRadioButtonId()==1 ? "枚" : "玉",optional(yen),optional(units));
            Catalog.add(db,"hall",hall.getText().toString());
        });
    }
    private void editBasics(String sessionId) throws Exception {
        JSONObject expected=store.metadata(sessionId);
        LinearLayout panel=form();
        label(panel,"ホール名の変更は、台移動でつながる記録にも反映します。登録済みの口座名は変更しません。");
        EditText hall=field(panel,"ホール",expected.optString("hall"));
        EditText machine=field(panel,"機種",expected.optString("machine"));
        EditText number=FormUi.machineNumber(activity,panel,"台番号",expected.optString("number"));
        EditText memo=field(panel,"メモ",expected.optString("memo")); memo.setSingleLine(false);
        JSONObject session=store.session(sessionId);
        String playDay=session.getString("date");
        java.time.ZoneId zone=java.time.ZoneId.systemDefault();
        boolean sameDay=java.time.Instant.ofEpochMilli(session.getLong("started_at")).atZone(zone).toLocalDate().toString().equals(playDay)
            &&(session.isNull("ended_at")||java.time.Instant.ofEpochMilli(session.getLong("ended_at")).atZone(zone).toLocalDate().toString().equals(playDay));
        if(sameDay){
            label(panel,"遊技日："+playDay);
            EditText begun=FormUi.time(activity,panel,"開始時刻",new java.text.SimpleDateFormat("HH:mm",Locale.JAPAN).format(new Date(session.getLong("started_at"))));
            EditText ended=session.isNull("ended_at")?null:FormUi.time(activity,panel,"終了時刻",new java.text.SimpleDateFormat("HH:mm",Locale.JAPAN).format(new Date(session.getLong("ended_at"))));
            dialog("記録の基本情報",panel,()->store.editBasicsTimed(sessionId,expected,hall.getText().toString(),machine.getText().toString(),FormUi.numberText(number),memo.getText().toString(),
                FormUi.dayTime(playDay,begun),ended==null?null:FormUi.dayTime(playDay,ended)));
        }else{
            FormUi.Moment begun=new FormUi.Moment(activity,panel,"開始",session.getLong("started_at"),false);
            FormUi.Moment ended=session.isNull("ended_at")?null:new FormUi.Moment(activity,panel,"終了",session.getLong("ended_at"),false);
            dialog("記録の基本情報",panel,()->store.editBasicsTimed(sessionId,expected,hall.getText().toString(),machine.getText().toString(),FormUi.numberText(number),memo.getText().toString(),begun.value(),ended==null?null:ended.value()));
        }
    }
}
