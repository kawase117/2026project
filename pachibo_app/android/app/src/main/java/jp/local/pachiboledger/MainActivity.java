package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.content.res.Configuration;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public final class MainActivity extends Activity {
    private static final int IMPORT_JSON = 10, EXPORT_JSON = 11, IMPORT_PCB = 12, EXPORT_CSV = 13, EXPORT_ALL = 14, IMPORT_MACHINES=15, IMPORT_ZIP=16, IMPORT_CSV=17;
    private LedgerDb db;
    private LinearLayout body;
    private LinearLayout actionBar;

    @Override public void onCreate(Bundle savedInstanceState) {
        String mode=getSharedPreferences("display",MODE_PRIVATE).getString("theme_mode","system");
        boolean systemDark=(getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;
        boolean dark="dark".equals(mode) || ("system".equals(mode) && systemDark);
        setTheme(dark?R.style.LedgerThemeDark:R.style.LedgerTheme);
        FormUi.configure(dark);
        super.onCreate(savedInstanceState);
        db = new LedgerDb(this);
        showCalendar();
    }

    private TextView text(String value, int size) {
        TextView view = new TextView(this);
        view.setText(value); view.setTextColor(FormUi.INK); view.setTextSize(size); view.setPadding(12, 9, 12, 9);
        return view;
    }

    private Button button(String label, Runnable action) {
        Button view = new Button(this);
        FormUi.styleButton(view);
        view.setText(label); view.setOnClickListener(v -> action.run());
        return view;
    }

    private void page() {
        LinearLayout shell = new LinearLayout(this);
        shell.setOrientation(LinearLayout.VERTICAL);
        shell.setBackgroundColor(FormUi.BG);
        shell.setPadding(12, 4, 12, 4);
        LinearLayout header=new LinearLayout(this);header.setGravity(android.view.Gravity.END);
        header.addView(button("設定",this::showData),new LinearLayout.LayoutParams(FormUi.dp(this,64),FormUi.dp(this,40)));
        shell.addView(header);
        ScrollView scroll = new ScrollView(this);
        body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(body); shell.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        actionBar=new LinearLayout(this);actionBar.setOrientation(LinearLayout.VERTICAL);
        shell.addView(actionBar);
        LinearLayout nav = new LinearLayout(this);
        nav.addView(button("カレンダー", this::showCalendar), new LinearLayout.LayoutParams(0, FormUi.dp(this,48), 1));
        nav.addView(button("分析", this::showReport), new LinearLayout.LayoutParams(0, FormUi.dp(this,48), 1));
        nav.addView(button("記録", this::showRecord), new LinearLayout.LayoutParams(0, FormUi.dp(this,48), 1));
        shell.addView(nav);
        setContentView(shell);
    }

    private void error(Exception exception) {
        new AlertDialog.Builder(this).setTitle("処理できませんでした")
            .setMessage(exception.getMessage()).setPositiveButton("閉じる", null).show();
    }

    private Map<String, String> tagNames() throws Exception {
        Map<String, String> result = new HashMap<>();
        JSONArray tags = db.tags();
        for (int i = 0; i < tags.length(); i++) {
            JSONObject tag = tags.getJSONObject(i);
            result.put(tag.getString("source_id"), tag.getString("name"));
        }
        return result;
    }

    private String tagText(JSONObject row, Map<String, String> names) {
        JSONArray ids = row.optJSONArray("tag_ids");
        if (ids == null) return "";
        List<String> tags = new ArrayList<>();
        for (int i = 0; i < ids.length(); i++) tags.add(names.getOrDefault(ids.optString(i), ids.optString(i)));
        return String.join(", ", tags);
    }

    private void showHistory() {
        page();
        body.addView(button("＋ 記録を追加", () -> edit(null)));
        try {
            List<JSONObject> rows = db.records();
            Map<String, String> names = tagNames();
            body.addView(text("全 " + rows.size() + " 件。直近100件を表示", 14));
            for (int i = 0; i < Math.min(100, rows.size()); i++) {
                JSONObject row = rows.get(i);
                String title = row.optString("date") + "  " + row.optString("hall") + "  " + row.optString("machine")
                    + " " + row.optString("machine_number") + "番\n"
                    + String.format("収支 %,d円  |  %s", row.optLong("profit_yen"), tagText(row, names))
                    + ("pcb_type_missing".equals(row.optString("match_status")) ? "  ⚠ 要確認" : "");
                body.addView(button(title, () -> edit(row)));
            }
        } catch (Exception exception) { error(exception); }
    }

    private void showRecord() {
        page();
        SessionScreen screen=new SessionScreen(this,db,this::showRecord);screen.render(body);
        try {
            List<UnifiedLedger.Row> rows=UnifiedLedger.rows(db);
            body.addView(text("全 "+rows.size()+" 件（直近100件）",18));
            for(int i=0;i<Math.min(100,rows.size());i++){
                UnifiedLedger.Row row=rows.get(i);
                String value=row.profit!=null?"収支 "+FormUi.money(row.profit):
                    "active".equals(row.status)?"遊技中":"review".equals(row.status)?"要確認・集計対象外":"計算待ち";
                String title=row.date+" "+row.hall+" ／ "+row.machine+" "+row.number+"番\n"+value+
                    "  "+TagPicker.display(db,row.tags);
                body.addView(button(title,()->{
                    if("session".equals(row.source))screen.recordActions(row.original);
                    else try{RecordEditor.show(this,db,row.original,this::showRecord);}catch(Exception error){error(error);}
                }));
            }
        }catch(Exception error){error(error);}
    }

    private void showCalendar() {
        showCalendar(LocalDate.now());
    }

    private void showCalendar(LocalDate date) {
        page();
        new CalendarScreen(this, db, this::editFromCalendar, this::startFromCalendar, date).render(body,actionBar);
    }

    private void editFromCalendar(JSONObject row, LocalDate date) {
        try { RecordEditor.show(this, db, row, () -> showCalendar(date)); }
        catch (Exception e) { error(e); }
    }

    private void startFromCalendar(LocalDate date) {
        try { SessionEditor.show(this,db,date,null,()->showCalendar(date)); }
        catch (Exception e) { error(e); }
    }

    private EditText field(LinearLayout parent, String label, String value, boolean multiLine) {
        parent.addView(text(label, 14));
        EditText input = new EditText(this);
        input.setSingleLine(!multiLine);
        input.setText(value == null ? "" : value);
        parent.addView(input);
        return input;
    }

    private void edit(JSONObject existing) {
        try { RecordEditor.show(this,db,existing,this::showHistory); }
        catch(Exception e) { error(e); }
    }

    private void showReport() {
        page();
        new SessionReportScreen(this,db,this::showCalendar,row->{
            if("session".equals(row.source))new SessionScreen(this,db,this::showReport).recordActions(row.original);
            else try{RecordEditor.show(this,db,row.original,this::showReport);}catch(Exception error){error(error);}
        }).render(body);
    }

    private void showLegacyReport() {
        page();
        body.addView(text("ぱち簿から移行した記録と、後から入力した記録の収支です。", 14));
        EditText from = FormUi.date(this,body,"開始日","",true);
        EditText to = FormUi.date(this,body,"終了日","",true);
        FormUi.label(this,body,"遊技種別");
        android.widget.Spinner game=new android.widget.Spinner(this);game.setContentDescription("遊技種別");
        game.setAdapter(new android.widget.ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,
            new String[]{"すべて","スロット","パチンコ","未分類"}));body.addView(game);
        EditText hall = FormUi.choice(this,db,body,"ホール","","hall",true);
        EditText machine = FormUi.choice(this,db,body,"機種","","machine",true,
            ()->{String selected=game.getSelectedItem().toString();return "スロット".equals(selected)||"パチンコ".equals(selected)?selected:null;},
            ()->hall.getText().toString().trim());
        EditText tag = field(body, "タグ名で絞る（完全一致）", "", false);
        LinearLayout result = new LinearLayout(this); result.setOrientation(LinearLayout.VERTICAL);
        body.addView(button("集計する", () -> {
            result.removeAllViews();
            try {
                Map<String, String> names = tagNames();
                List<JSONObject> chosen = new ArrayList<>();
                long profit = 0; int wins = 0;
                Map<String, Long> byMonth = new java.util.TreeMap<>();
                Map<String, long[]> byHall = new HashMap<>();
                Map<String, long[]> byMachine = new HashMap<>();
                for (JSONObject row : db.records()) {
                    String date = row.optString("date");
                    if (!from.getText().toString().isEmpty() && date.compareTo(from.getText().toString()) < 0) continue;
                    if (!to.getText().toString().isEmpty() && date.compareTo(to.getText().toString()) > 0) continue;
                    if (!"すべて".equals(game.getSelectedItem().toString()) && !row.optString("kind").equals(game.getSelectedItem().toString())) continue;
                    if (!hall.getText().toString().isEmpty() && !row.optString("hall").equals(hall.getText().toString())) continue;
                    if (!machine.getText().toString().isEmpty() && !row.optString("machine").equals(machine.getText().toString())) continue;
                    String exactTag = tag.getText().toString().trim();
                    if (!exactTag.isEmpty()) {
                        boolean found = false;
                        for (String id : TagPicker.ids(row.optJSONArray("tag_ids"))) if (exactTag.equals(names.get(id))) found = true;
                        if (!found) continue;
                    }
                    if ("pcb_type_missing".equals(row.optString("match_status"))) continue;
                    chosen.add(row);
                    long gain = row.optLong("profit_yen"); profit += gain;
                    if (gain > 0) wins++;
                    byMonth.merge(date.substring(0, 7), gain, Long::sum);
                    long[] hallStats = byHall.computeIfAbsent(row.optString("hall"), key -> new long[2]);
                    hallStats[0] += gain; hallStats[1]++;
                    long[] machineStats = byMachine.computeIfAbsent(row.optString("machine"), key -> new long[2]);
                    machineStats[0] += gain; machineStats[1]++;
                }
                result.addView(text(String.format("%d件  収支 %,d円  勝率 %.1f%%", chosen.size(), profit,
                    chosen.isEmpty() ? 0 : wins * 100.0 / chosen.size()), 18));
                ProfitChart chart = new ProfitChart(this); chart.setRows(chosen);
                result.addView(chart, new LinearLayout.LayoutParams(-1, 500));
                result.addView(text("月別収支", 18));
                HorizontalScrollView strip = new HorizontalScrollView(this);
                MonthlyChart monthly = new MonthlyChart(this); monthly.setMonths(byMonth);
                strip.addView(monthly, new android.widget.FrameLayout.LayoutParams(Math.max(700, byMonth.size() * 90), 430));
                result.addView(strip);
                for (Map.Entry<String, Long> month : byMonth.entrySet())
                    result.addView(text(String.format("%s   %,d円", month.getKey(), month.getValue()), 15));
                addBreakdown(result, "ホール別", byHall);
                addBreakdown(result, "機種別", byMachine);
            } catch (Exception exception) { error(exception); }
        }));
        body.addView(result);
    }

    private void addBreakdown(LinearLayout target, String title, Map<String, long[]> groups) {
        target.addView(text(title + "（収支上位・下位）", 18));
        List<Map.Entry<String, long[]>> sorted = new ArrayList<>(groups.entrySet());
        sorted.sort((a, b) -> Long.compare(b.getValue()[0], a.getValue()[0]));
        for (int i = 0; i < sorted.size(); i++) {
            if (i >= 5 && i < sorted.size() - 5) continue;
            Map.Entry<String, long[]> entry = sorted.get(i);
            long[] stats = entry.getValue();
            target.addView(text(String.format("%s  %,d円  %d件  平均%,d円", entry.getKey(), stats[0],
                stats[1], stats[1] == 0 ? 0 : stats[0] / stats[1]), 14));
        }
    }

    private void showData() {
        page();
        String mode=getSharedPreferences("display",MODE_PRIVATE).getString("theme_mode","system");
        body.addView(button("表示："+("dark".equals(mode)?"ダーク":"light".equals(mode)?"ライト":"端末設定に合わせる"),()->{
            String[] options={"端末設定に合わせる","ライト","ダーク"};
            new AlertDialog.Builder(this).setTitle("表示テーマ").setSingleChoiceItems(options,"dark".equals(mode)?2:"light".equals(mode)?1:0,
                (dialog,which)->{
                    getSharedPreferences("display",MODE_PRIVATE).edit().putString("theme_mode",new String[]{"system","light","dark"}[which]).apply();
                    dialog.dismiss();recreate();
                }).setNegativeButton("戻る",null).show();
        }));
        body.addView(text("入力画面に表示する項目",18));
        for(String[] option:new String[][]{{"number","台番号を表示"},{"time","開始・終了時刻を表示"},
            {"advanced","回転数・仕事量を表示"}}){
            String key=option[0];
            boolean checked="number".equals(key)?EntryPreferences.number(this):
                "time".equals(key)?EntryPreferences.time(this):EntryPreferences.advanced(this);
            android.widget.CheckBox toggle=new android.widget.CheckBox(this);
            toggle.setText(option[1]);toggle.setTextColor(FormUi.INK);toggle.setChecked(checked);
            toggle.setOnCheckedChangeListener((view,value)->EntryPreferences.set(this,key,value));
            body.addView(toggle);
        }
        body.addView(text("時刻を隠して記録した遊技は稼働時間の分析から除外します。隠した項目の既存データは残ります。",13));
        body.addView(text("機種一覧：記録した機種は次回から選択できます。新台は手入力で追加するか、UTF-8のテキスト（1行1機種名）を読み込めます。",14));
        body.addView(button("機種名一覧を読み込む",()->{
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);intent.setType("text/*");startActivityForResult(intent,IMPORT_MACHINES);
        }));
        body.addView(text("ぱち簿の .pcb バックアップを直接読み込めます。同じIDで内容が一致する記録は追加せず、内容が異なる場合は上書きせず取り込みを取り消します。", 15));
        body.addView(button("全データをZIPで保存（Dropboxなどを選択可）", () -> {
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("application/zip");
            intent.putExtra(Intent.EXTRA_TITLE,"pachibo-ledger-complete.zip");
            startActivityForResult(intent,EXPORT_ALL);
        }));
        body.addView(button("ぱち簿 .pcb を読み込む", () -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("*/*");
            startActivityForResult(intent, IMPORT_PCB);
        }));
        body.addView(button("JSONを読み込む", () -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("application/json");
            startActivityForResult(intent, IMPORT_JSON);
        }));
        body.addView(button("全データZIPを復元", () -> {
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("application/zip");startActivityForResult(intent,IMPORT_ZIP);
        }));
        body.addView(button("他アプリのCSVを読み込む", () -> {
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT);intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("text/*");startActivityForResult(intent,IMPORT_CSV);
        }));
        body.addView(button("全項目をJSONで保存", () -> {
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("application/json");
            intent.putExtra(Intent.EXTRA_TITLE, "pachibo-ledger-backup.json");
            startActivityForResult(intent, EXPORT_JSON);
        }));
        body.addView(button("全記録を1つのCSVで保存", () -> {
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("text/csv");
            intent.putExtra(Intent.EXTRA_TITLE, "pachibo-ledger-all-records.csv");
            startActivityForResult(intent, EXPORT_CSV);
        }));
        body.addView(text("Androidの保存先選択画面から、端末内やDropboxなどの対応サービスを選べます。自動同期は行いません。JSON・ZIPは件数と期間を確認してから復元します。ZIPには全テーブルCSV、小役カウンタ、タグ関係、復元用backup.json、保存済みの取り込み原本を含みます。以前の版で取り込んだ原本は自動で復元できないため、元の.pcbを再度読み込んでください。", 14));
    }

    private static String csvCell(String value) {
        return "\"" + (value == null ? "" : value.replace("\"", "\"\"")) + "\"";
    }

    private String recordCsv() throws Exception {
        return ExportBundle.csv(UnifiedLedger.export(UnifiedLedger.rows(db),tagNames(),db),"id","date","hall","kind",
            "machine","machine_number","investment_total_yen","recovery_total_yen","profit_yen",
            "spins","work_yen","work_source","work_equal_border","work_rotation_rate",
            "work_holding_percent","work_exchange_yen","work_exchange_balls",
            "status","tag_ids","tag_names","memo","counters");
    }

    private void importData(android.net.Uri uri, boolean pcb, boolean zip) {
        Toast.makeText(this, "読み込み中です。完了までお待ちください", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try (InputStream input = getContentResolver().openInputStream(uri)) {
                if (input == null) throw new IllegalStateException("ファイルを開けません");
                JSONObject imported=pcb?PcbReader.parse(input):zip?BackupIO.readZip(input,getCacheDir()):BackupIO.readJson(input);
                BackupIO.validate(imported);
                String preview=BackupIO.preview(imported);
                runOnUiThread(()->new AlertDialog.Builder(this).setTitle("取り込み前の確認")
                    .setMessage(preview).setNegativeButton("取り消す",null)
                    .setPositiveButton("取り込む",(dialog,which)->commitImport(imported,pcb)).show());
            } catch (Exception exception) { runOnUiThread(() -> error(exception)); }
        },"ledger-import-preview").start();
    }

    private void commitImport(JSONObject imported,boolean pcb){
        Toast.makeText(this,"取り込み中です。完了までお待ちください",Toast.LENGTH_SHORT).show();
        new Thread(()->{
            try{
                int count=db.importJson(imported);
                JSONObject entrySettings=imported.optJSONObject("entry_preferences");
                if(entrySettings!=null){
                    for(String key:new String[]{"number","time","advanced"})
                        if(entrySettings.has(key))EntryPreferences.set(this,key,entrySettings.optBoolean(key));
                }
                JSONObject audit = imported.optJSONObject("audit");
                String detail = pcb && audit != null ? "。要確認 " + audit.optInt("review_required_records") +
                    "件、文字数不一致 " + audit.optInt("bad_length_fields") + "件" : "";
                runOnUiThread(() -> {
                    showCalendar();
                    Toast.makeText(this, count + "件を読み込みました" + detail, Toast.LENGTH_LONG).show();
                });
            } catch (Exception exception) { runOnUiThread(() -> error(exception)); }
        },"ledger-import-commit").start();
    }

    private void importCsv(android.net.Uri uri){
        new Thread(()->{
            try(InputStream stream=getContentResolver().openInputStream(uri)){
                if(stream==null)throw new IllegalArgumentException("CSVを開けません");
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[16384];int n;
                while((n=stream.read(buffer))!=-1){
                    if(bytes.size()+n>16*1024*1024)throw new IllegalArgumentException("CSVが16MBを超えています");
                    bytes.write(buffer,0,n);
                }
                GenericCsv csv=new GenericCsv(bytes.toByteArray());
                runOnUiThread(()->showCsvMapping(csv));
            }catch(Exception e){runOnUiThread(()->error(e));}
        },"csv-read").start();
    }

    private void showCsvMapping(GenericCsv csv){
        android.widget.LinearLayout panel=new android.widget.LinearLayout(this);panel.setOrientation(1);
        panel.setPadding(20,8,20,8);
        android.widget.ScrollView scroll=new android.widget.ScrollView(this);scroll.addView(panel);
        String[] options=new String[csv.headers().size()+1];options[0]="（列なし）";
        final AlertDialog[] mappingDialog=new AlertDialog[1];
        for(int i=0;i<csv.headers().size();i++)options[i+1]=(i+1)+"："+csv.headers().get(i);
        android.widget.Spinner[] selectors=new android.widget.Spinner[GenericCsv.FIELDS.length];
        for(int i=0;i<selectors.length;i++){
            panel.addView(text(GenericCsv.FIELDS[i]+(i<5?"（必須）":"（任意）"),14));
            android.widget.Spinner spinner=new android.widget.Spinner(this);
            spinner.setAdapter(new android.widget.ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,options));
            spinner.setSelection(csv.suggested(i)+1);panel.addView(spinner);selectors[i]=spinner;
        }
        android.widget.TextView preview=text("列を選んで『内容を確認』を押してください。",14);panel.addView(preview);
        panel.addView(button("内容を確認",()->{
            int[] mapping=new int[selectors.length];for(int i=0;i<mapping.length;i++)mapping[i]=selectors[i].getSelectedItemPosition()-1;
            preview.setText("CSV全件を確認しています…\n"+csv.sample(mapping));
            new Thread(()->{try{
                Map<String,String> known=new HashMap<>();
                for(JSONObject tag:jsonRows(db.tags()))known.put(tag.getString("name"),tag.getString("source_id"));
                JSONObject converted=csv.convert(mapping,known);
                JSONArray rows=converted.getJSONArray("records");String first=null,last=null;
                for(int i=0;i<rows.length();i++){
                    String date=rows.getJSONObject(i).getString("date");
                    if(first==null||date.compareTo(first)<0)first=date;
                    if(last==null||date.compareTo(last)>0)last=date;
                }
                String summary=rows.length()+"件 / "+(first==null?"記録なし":first+" ～ "+last)+"\n"
                    +"遊技種別などCSVにない値は推測せず未分類のまま保持します。\n\n"+csv.sample(mapping);
                runOnUiThread(()->{preview.setText(csv.sample(mapping));
                    new AlertDialog.Builder(this).setTitle("CSV取り込み前の確認").setMessage(summary)
                    .setNegativeButton("戻る",null).setPositiveButton("取り込む",(d,w)->{
                        mappingDialog[0].dismiss();
                        new Thread(()->{try{int count=db.importCsv(converted);
                            runOnUiThread(()->{showCalendar();Toast.makeText(this,count+"件を読み込みました",Toast.LENGTH_LONG).show();});
                        }catch(Exception e){runOnUiThread(()->error(e));}},"csv-import").start();
                    }).show();});
            }catch(Exception e){runOnUiThread(()->error(e));}},"csv-preview").start();
        }));
        mappingDialog[0]=new AlertDialog.Builder(this).setTitle("CSVの列対応")
            .setView(scroll).setPositiveButton("閉じる",null).create();
        mappingDialog[0].show();
    }

    private static List<JSONObject> jsonRows(JSONArray array)throws Exception{
        List<JSONObject> rows=new ArrayList<>();for(int i=0;i<array.length();i++)rows.add(array.getJSONObject(i));return rows;
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        try {
            if(requestCode==IMPORT_MACHINES){
                final android.net.Uri uri=data.getData();
                new Thread(()->{try(java.io.BufferedReader reader=new java.io.BufferedReader(new java.io.InputStreamReader(getContentResolver().openInputStream(uri),StandardCharsets.UTF_8))){
                    android.database.sqlite.SQLiteDatabase writable=db.getWritableDatabase();writable.beginTransaction();int count=0;
                    try{String line;while((line=reader.readLine())!=null){line=line.replace("\ufeff","").trim();if(!line.isEmpty()){Catalog.add(db,"machine",line);count++;}}writable.setTransactionSuccessful();}finally{writable.endTransaction();}
                    final int read=count;runOnUiThread(()->Toast.makeText(this,read+"行の機種名を読み込みました（同名は重複登録しません）",Toast.LENGTH_LONG).show());
                }catch(Exception e){runOnUiThread(()->error(e));}},"machine-catalog").start();
            } else if (requestCode == IMPORT_PCB) {
                importData(data.getData(), true,false);
            } else if (requestCode == IMPORT_JSON) {
                importData(data.getData(), false,false);
            } else if(requestCode==IMPORT_ZIP){
                importData(data.getData(),false,true);
            } else if(requestCode==IMPORT_CSV){
                importCsv(data.getData());
            } else if (requestCode == EXPORT_ALL) {
                exportBackup(data.getData(),true);
            } else if (requestCode == EXPORT_JSON) {
                exportBackup(data.getData(),false);
            } else if (requestCode == EXPORT_CSV) {
                exportCsv(data.getData());
            }
        } catch (Exception exception) { error(exception); }
    }

    private void exportBackup(android.net.Uri uri, boolean zip) {
        Toast.makeText(this,"出力しています。完了までお待ちください",Toast.LENGTH_LONG).show();
        new Thread(() -> {
            try (OutputStream output=getContentResolver().openOutputStream(uri)) {
                if(output==null) throw new IllegalStateException("ファイルを保存できません");
                JSONObject snapshot;JSONArray combined=null;
                if(zip){
                    android.database.sqlite.SQLiteDatabase sqlite=db.getWritableDatabase();sqlite.beginTransaction();
                    try{snapshot=db.backup();combined=UnifiedLedger.export(UnifiedLedger.rows(db),tagNames(),db);sqlite.setTransactionSuccessful();}
                    finally{sqlite.endTransaction();}
                    snapshot.put("entry_preferences",entryPreferencesSnapshot());
                    ExportBundle.write(snapshot,output,combined);
                }else snapshot=db.backup().put("entry_preferences",entryPreferencesSnapshot());
                if(!zip)
                    output.write(snapshot.toString(2).getBytes(StandardCharsets.UTF_8));
                runOnUiThread(() -> Toast.makeText(this,"保存しました",Toast.LENGTH_LONG).show());
            } catch(Exception error) { runOnUiThread(() -> error(error)); }
        },"ledger-export").start();
    }
    private JSONObject entryPreferencesSnapshot()throws Exception {
        return new JSONObject().put("number",EntryPreferences.number(this))
            .put("time",EntryPreferences.time(this)).put("advanced",EntryPreferences.advanced(this));
    }
    private void exportCsv(android.net.Uri uri) {
        Toast.makeText(this,"CSVを出力しています",Toast.LENGTH_SHORT).show();
        new Thread(()->{
            try(OutputStream output=getContentResolver().openOutputStream(uri)){
                if(output==null)throw new IllegalStateException("ファイルを保存できません");
                output.write(recordCsv().getBytes(StandardCharsets.UTF_8));
                runOnUiThread(()->Toast.makeText(this,"CSVを保存しました",Toast.LENGTH_LONG).show());
            }catch(Exception error){runOnUiThread(()->error(error));}
        },"ledger-csv-export").start();
    }
}
