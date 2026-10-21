package jp.local.pachiboledger;

import android.app.Instrumentation;
import android.os.Bundle;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;

/** Explicit test runner: only touches two test-named databases, never ledger.db. */
public final class BackupVerification extends Instrumentation {
    private boolean realPcb;
    @Override public void onCreate(Bundle args) { super.onCreate(args); realPcb=args!=null&&"true".equals(args.getString("real_pcb")); start(); }
    private static void check(boolean value,String message) { if(!value) throw new AssertionError(message); }
    private static void pcbField(StringBuilder out,String key,String value) {
        if(out.length()>0)out.append(',');
        out.append("String,").append(key).append(',').append(value.length()).append(',').append(value);
    }
    @Override public void onStart() {
        waitForIdleSync();
        if(realPcb) { verifyRealPcb(); return; }
        Bundle result=new Bundle(); Context context=getTargetContext();
        String nameA="verification-source.db",nameB="verification-restore.db";
        context.deleteDatabase(nameA); context.deleteDatabase(nameB);
        try(LedgerDb source=new LedgerDb(context,nameA); LedgerDb restored=new LedgerDb(context,nameB)) {
            verifyAnalysisMetrics(context);
            boolean[] numericUi=new boolean[3];
            String[] numericObserved=new String[2];
            runOnMainSync(()->{
                android.widget.EditText number=new android.widget.EditText(context);FormUi.numeric(number);
                number.setText("１２,３４５abc");numericUi[0]="12,345".equals(number.getText().toString());
                numericObserved[0]=number.getText().toString()+" type="+number.getInputType();
                numericUi[1]=(number.getInputType()&android.text.InputType.TYPE_MASK_CLASS)==android.text.InputType.TYPE_CLASS_NUMBER;
                number.setText("abc");numericUi[2]=number.getText().toString().isEmpty();
                numericObserved[1]=number.getText().toString();
            });
            check(numericUi[0]&&numericUi[1]&&numericUi[2],"Numeric keyboard, grouping or character restriction failed: "+Arrays.toString(numericUi)+" "+Arrays.toString(numericObserved));
            boolean[] machineNumberUi=new boolean[2];
            runOnMainSync(()->{
                android.widget.EditText machineNumber=new android.widget.EditText(context);
                FormUi.machineNumber(machineNumber);
                machineNumber.setText("００１２abc");machineNumberUi[0]="0012".equals(FormUi.numberText(machineNumber));
                machineNumberUi[1]=(machineNumber.getInputType()&android.text.InputType.TYPE_MASK_CLASS)==android.text.InputType.TYPE_CLASS_NUMBER;
            });
            check(machineNumberUi[0]&&machineNumberUi[1],"Machine number input did not preserve leading zeros or reject letters");
            String tag=source.tagId("朝一,特日\n🎰\"試験\"");
            SessionStore store=new SessionStore(source);
            JSONObject meta=new JSONObject().put("hall","試験店").put("machine","試験機種").put("number","001")
                .put("memo","改行\nカンマ,引用\"絵文字🎰").put("tag_ids",new JSONArray().put(tag));
            store.start("A","2026-10-18","slot-56",meta);
            store.add("cash","A",true,-10000,null,null);
            store.move("A","B","transfer",600L,20L,1L,meta);
            store.finish("B","finish",16000L,0L,null,null);
            // Simulate the previous installed schema and reopen through SQLiteOpenHelper.
            source.getWritableDatabase().execSQL("DROP TABLE edit_history");
            source.getWritableDatabase().execSQL("DROP TABLE accounts");
            source.getWritableDatabase().execSQL("DROP TABLE record_details");
            source.getWritableDatabase().execSQL("DROP TABLE catalog");
            source.getWritableDatabase().execSQL("DROP TABLE counters");
            source.getWritableDatabase().setVersion(3); source.close();
            check(store.history("A").isEmpty(),"v3 migration failed");
            check(store.details("A",true).size()==1,"Migration lost transfer");
            AccountStore accounts=new AccountStore(source);
            accounts.save("account-test",null,"試験店","46枚,口座","枚",20L,1L);
            JSONObject account=accounts.list().get(0);
            store.patchMetadata("A",AccountStore.snapshot(account,new JSONObject()));
            accounts.save("account-test",account,"試験店","46枚,口座","枚",10L,1L);
            check(store.metadata("A").getLong("default_rate_yen")==20,"Account edit changed session defaults");
            check(store.calculate(Collections.singleton("A")).evaluated.roundYen().equals(java.math.BigInteger.valueOf(2000)),"Account edit changed old profit");
            check(AccountStore.snapshot(accounts.list().get(0),new JSONObject()).getLong("default_rate_yen")==10,"New snapshot lost edited rate");
            JSONObject basicBefore=store.metadata("A");
            store.editBasics("A",basicBefore,"訂正店","修正台","002","修正メモ");
            check("訂正店".equals(store.metadata("B").getString("hall")),"Linked hall name not updated");
            check(store.metadata("A").getJSONArray("tag_ids").getString(0).equals(tag),"Basic edit lost tags");
            store.patchMetadata("A",new JSONObject().put("memo","追加メモ"));
            check("修正台".equals(store.metadata("A").getString("machine")),"Memo update lost machine");
            boolean staleBasic=false;
            try { store.editBasics("A",basicBefore,"古い店","古い台","003",""); } catch(IllegalStateException expected) { staleBasic=true; }
            check(staleBasic,"Stale basic edit accepted");
            check(AmountInput.signed("9223372036854775808",true)==Long.MIN_VALUE,"Expense limit failed");
            for(String invalid:new String[]{"-1","","1.5","9223372036854775808"}) {
                boolean rejectedInput=false; try { AmountInput.signed(invalid,false); } catch(IllegalArgumentException expected) { rejectedInput=true; }
                check(rejectedInput,"Invalid unsigned amount accepted");
            }
            JSONObject transferBefore=store.details("A",true).get(0);
            store.correct(transferBefore,true,500L,20L,1L);
            check(store.calculate(Collections.singleton("A")).evaluated.roundYen().equals(java.math.BigInteger.ZERO),"Outgoing correction missing");
            check(store.calculate(Collections.singleton("B")).evaluated.roundYen().equals(java.math.BigInteger.valueOf(6000)),"Incoming correction missing");
            check(store.calculate(new HashSet<>(Arrays.asList("A","B"))).evaluated.roundYen().equals(java.math.BigInteger.valueOf(6000)),"Transfer correction changed total");
            String corrected=source.backup().toString(); boolean staleRejected=false;
            try { store.correct(transferBefore,true,700L,20L,1L); } catch(IllegalStateException expected) { staleRejected=true; }
            check(staleRejected && corrected.equals(source.backup().toString()),"Stale correction was not rejected atomically");
            JSONObject transferCurrent=store.details("B",true).get(0);
            boolean badRate=false;
            try { store.correct(transferCurrent,true,500L,20L,null); } catch(IllegalArgumentException expected) { badRate=true; }
            check(badRate && corrected.equals(source.backup().toString()),"Invalid rate changed data");
            store.correct(transferCurrent,true,null,null,null);
            check(store.calculate(Collections.singleton("A")).evaluated==null,"Unknown quantity treated as zero");
            check(store.calculate(new HashSet<>(Arrays.asList("A","B"))).evaluated.roundYen().equals(java.math.BigInteger.valueOf(6000)),"Unknown internal transfer did not cancel");
            store.correct(store.details("A",true).get(0),true,600L,20L,1L);
            JSONObject cashBefore=store.details("A",false).get(0);
            store.correct(cashBefore,false,-9000L,null,null);
            check(store.calculate(Collections.singleton("A")).cash.equals(java.math.BigInteger.valueOf(-9000)),"Cash correction missing");
            store.correct(store.details("A",false).get(0),false,-10000L,null,null);
            String cashEdit=store.history("A").get(0).getString("id");
            store.undo(cashEdit);
            check(store.calculate(Collections.singleton("A")).cash.equals(java.math.BigInteger.valueOf(-9000)),"Undo cash failed");
            String afterUndo=source.backup().toString(); boolean oldUndoRejected=false;
            try { store.undo(cashEdit); } catch(IllegalStateException expected) { oldUndoRejected=true; }
            check(oldUndoRejected && afterUndo.equals(source.backup().toString()),"Repeated undo changed data");
            store.undo(store.history("A").get(0).getString("id"));
            check(store.calculate(Collections.singleton("A")).cash.equals(java.math.BigInteger.valueOf(-10000)),"Undo reversal failed");
            String atomicBefore=source.backup().toString();
            source.getWritableDatabase().execSQL("CREATE TEMP TRIGGER fail_history BEFORE INSERT ON edit_history BEGIN SELECT RAISE(ABORT,'test failure'); END");
            boolean historyFailed=false;
            try { store.correct(store.details("A",false).get(0),false,-1L,null,null); }
            catch(android.database.sqlite.SQLiteException expected) { historyFailed=true; }
            source.getWritableDatabase().execSQL("DROP TRIGGER fail_history");
            check(historyFailed && atomicBefore.equals(source.backup().toString()),"History failure did not roll back correction");
            String plain="String,unknown_setting,4,🎰,x,String,hall1_name,8,TestHall,Integer,hall1_invest_conversion_slot,4,1923,Integer,hall1_recovery_conversion_slot,4,1923,Integer,item20261018_0_type,1,1,Integer,item20261018_0_hall_id,1,1,Integer,item20261018_0_invest_conversion,4,1923,Integer,item20261018_0_invest,4,1000,Integer,item20261018_0_recovery,4,2000,Integer,item20261018_0_start,4,1331,Integer,item20261018_0_end,4,1439";
            byte[] pcb=plain.getBytes(StandardCharsets.UTF_8); for(int i=0;i<pcb.length;i++) pcb[i]=(byte)(pcb[i]^255);
            JSONObject imported=PcbReader.parse(new ByteArrayInputStream(pcb));
            check(imported.getJSONArray("records").length()==1,"PCB play record not parsed");
            check("スロット".equals(imported.getJSONArray("records").getJSONObject(0).getString("kind")),"PCB hall conversion did not classify slot");
            StringBuilder historic=new StringBuilder();
            for(String[] field:new String[][]{
                {"hall1_invest_conversion_slot","500"},{"hall1_recovery_conversion_slot","500"},
                {"hall2_invest_conversion_slot","1923"},{"hall2_recovery_conversion_slot","1923"},
                {"hall3_invest_conversion_pachi","100"},{"hall3_recovery_conversion_pachi","93"},
                {"hall4_invest_conversion_pachi","357"},{"hall4_recovery_conversion_pachi","357"}})
                pcbField(historic,field[0],field[1]);
            String[] hallIds={"1","2","3","4"}, rates={"500","500","100","100"}, returns={"500","500","93","93"};
            for(int n=0;n<4;n++) {
                String prefix="item20261018_"+n+"_";
                pcbField(historic,prefix+"type","1");pcbField(historic,prefix+"hall_id",hallIds[n]);
                pcbField(historic,prefix+"machine_id",Integer.toString(n+1));
                pcbField(historic,prefix+"invest_conversion",rates[n]);
                pcbField(historic,prefix+"recovery_conversion",returns[n]);
                pcbField(historic,prefix+"invest","1000");pcbField(historic,prefix+"recovery","2000");
            }
            byte[] oldRates=historic.toString().getBytes(StandardCharsets.UTF_8);
            for(int n=0;n<oldRates.length;n++)oldRates[n]=(byte)(oldRates[n]^255);
            JSONObject historical=PcbReader.parse(new ByteArrayInputStream(oldRates));
            JSONArray historicalRecords=historical.getJSONArray("records");
            check(historicalRecords.length()==4,"Historical rate fixture not parsed");
            for(int n=0;n<4;n++)
                check((n<2?"スロット":"パチンコ").equals(historicalRecords.getJSONObject(n).getString("kind")),
                    "Historical rate did not identify the game kind for item "+n);
            check(historical.getJSONObject("audit").getInt("game_kind_from_historical_rate")==2,
                "Historical conversion evidence was not used for both old-rate records");
            JSONObject oldImport=new JSONObject(imported.toString());
            oldImport.getJSONArray("records").getJSONObject(0).put("kind","未分類");
            source.importJson(oldImport);
            JSONObject legacyTime=source.recordDetails("pcb-20261018_0");
            check(legacyTime.getLong("ended_at")-legacyTime.getLong("started_at")==68*60000L,
                "PCB start/end were not imported for hourly analysis");
            android.content.ContentValues editedDetails=new android.content.ContentValues();
            editedDetails.put("id","pcb-20261018_0");
            editedDetails.put("payload",new JSONObject().put("mixed_inputs",true)
                .put("unallocated_investment_yen","1000").toString());
            source.getWritableDatabase().insertWithOnConflict("record_details",null,editedDetails,
                android.database.sqlite.SQLiteDatabase.CONFLICT_REPLACE);
            JSONObject legacy=new JSONObject().put("id","legacy").put("date","2026-10-17").put("hall","試験店")
                .put("kind","スロット").put("machine","試験機種").put("investment_yen",1000).put("recovery_yen",2000)
                .put("profit_yen",1000).put("memo",JSONObject.NULL).put("tag_ids",new JSONArray().put(tag));
            imported.getJSONArray("records").put(legacy); source.importJson(imported);
            check("スロット".equals(source.records().get(0).optString("kind")),"Existing PCB record was not classified on reimport");
            JSONObject mergedTime=source.recordDetails("pcb-20261018_0");
            check(mergedTime.optBoolean("mixed_inputs")
                &&mergedTime.getLong("ended_at")-mergedTime.getLong("started_at")==68*60000L,
                "Repeat PCB import did not preserve edits while filling missing times");
            List<UnifiedLedger.Row> analysisRows=new ArrayList<>();
            for(Object[] item:new Object[][]{
                {"day-1","2026-10-01",10000L,false,3600000L},
                {"day-2","2026-10-02",-20000L,false,0L},
                {"cost","2026-10-02",-2000L,true,0L},
                {"day-3","2026-10-03",5000L,false,0L}}){
                JSONObject record=new JSONObject().put("id",item[0]).put("date",item[1])
                    .put("hall","試験店").put("machine","試験機種").put("kind","スロット")
                    .put("profit_yen",item[2]).put("tag_ids",new JSONArray());
                JSONObject details=new JSONObject().put("expense",item[3]);
                if((long)item[4]>0)details.put("started_at",0).put("ended_at",item[4]);
                analysisRows.add(new UnifiedLedger.Row(record,false,null,details));
            }
            AnalysisMetrics.Stats metrics=AnalysisMetrics.calculate(analysisRows);
            check(metrics.playCount==3&&metrics.expenseCount==1
                &&metrics.playProfit.equals(java.math.BigInteger.valueOf(-5000))
                &&metrics.total().equals(java.math.BigInteger.valueOf(-7000))
                &&metrics.medianPlay.equals(java.math.BigInteger.valueOf(5000))
                &&metrics.maxDrawdown.equals(java.math.BigInteger.valueOf(22000))
                &&metrics.hourly().equals(java.math.BigInteger.valueOf(10000))
                &&metrics.winningPlays==2&&metrics.winningDays==2,
                "Analysis costs, hourly sample, median, win counts or drawdown are wrong");
            check(AmountInput.signed("１２,３４５",false)==12345,"Number normalization failed");
            Catalog.add(source,"machine","新台テスト");Catalog.add(source,"machine","新台テスト");
            check(Catalog.names(source,"machine").contains("新台テスト"),"Catalog missing");
            JSONObject inputs=new JSONObject().put("investment_input","50").put("investment_unit","枚").put("recovery_input","100").put("recovery_unit","枚").put("rate_yen","20").put("rate_units","1").put("started_at",1000).put("ended_at",61000);
            source.saveRecord(legacy,inputs);source.save(legacy);
            check(source.recordDetails("legacy").toString().equals(inputs.toString()),"Legacy edit lost units or timing");
            store.startAt("timed","2026-10-19","account-test",new JSONObject(),1000L);
            String beforeBadTime=source.backup().toString();boolean badTime=false;
            try { store.finishAt("timed","clock-finish",0L,100L,20L,1L,900L); }catch(IllegalArgumentException expected){badTime=true;}
            check(badTime && beforeBadTime.equals(source.backup().toString()),"Invalid time not atomic");
            store.finishAt("timed","clock-finish",0L,100L,20L,1L,61000L);
            check(store.session("timed").getLong("ended_at")-store.session("timed").getLong("started_at")==60000L,"Selected times lost");
            long mixedStart=java.time.LocalDate.of(2026,10,19).atTime(10,0)
                .atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
            store.startAt("mixed","2026-10-19","account-test",new JSONObject().put("hall","試験店")
                .put("machine","混合入力機種").put("game_kind","スロット"),mixedStart);
            JSONObject mixedBefore=source.backup();boolean wrongDay=false;
            try{store.finishWithAmountsAt("mixed","mixed-fail",10000,100,5000,200,20L,1L,
                "終了メモ",new JSONArray().put(tag),mixedStart+86400000L);}catch(IllegalArgumentException expected){wrongDay=true;}
            check(wrongDay&&mixedBefore.toString().equals(source.backup().toString()),"Different-day finish changed records");
            store.finishWithAmountsAt("mixed","mixed-finish",10000,100,5000,200,20L,1L,
                "終了メモ",new JSONArray().put(tag),mixedStart+3600000L);
            check(store.calculate(Collections.singleton("mixed")).evaluated.roundYen().equals(java.math.BigInteger.valueOf(-3000)),"Mixed cash and medals profit failed");
            check("終了メモ".equals(store.metadata("mixed").getString("memo"))&&store.metadata("mixed").getJSONArray("tag_ids").getString(0).equals(tag),"Finish memo/tags lost");
            check(store.details("mixed",false).size()==4,"Mixed finish did not retain four amounts");
            JSONObject editMeta=new JSONObject().put("hall","試験店").put("machine","編集前")
                .put("number","100").put("game_kind","スロット").put("memo","").put("tag_ids",new JSONArray());
            store.startAt("editor-test","2026-10-19","account-test",editMeta,mixedStart);
            store.completeEdited("editor-test",editMeta,accounts.forHall("試験店","スロット"),"試験店","編集後","101","スロット","終了時メモ",
                new JSONArray().put(tag),mixedStart,mixedStart+3600000L,"editor-operation",1000,50,0,100,20L,1L);
            check("ended".equals(store.session("editor-test").getString("state"))
                &&"編集後".equals(store.metadata("editor-test").getString("machine"))
                &&store.calculate(Collections.singleton("editor-test")).evaluated.roundYen().longValue()==0,
                "Unified editor completion failed");
            store.reviseCompleted("editor-test",store.metadata("editor-test"),accounts.forHall("試験店","スロット"),
                "試験店","編集後","101","訂正メモ",new JSONArray().put(tag),mixedStart,mixedStart+3600000L,
                500,50,0,100,10L,1L);
            check(store.calculate(Collections.singleton("editor-test")).evaluated.roundYen().longValue()==500,
                "Completed cash correction changed unchanged quantity valuation");
            store.reviseCompleted("editor-test",store.metadata("editor-test"),accounts.forHall("試験店","スロット"),
                "試験店","編集後","101","訂正メモ",new JSONArray().put(tag),mixedStart,mixedStart+3600000L,
                500,60,0,100,10L,1L);
            check(store.calculate(Collections.singleton("editor-test")).evaluated.roundYen().longValue()==900
                &&!store.history("editor-test").isEmpty(),"Completed quantity correction lost history or rate");
            store.deleteSession("editor-test");
            boolean removed=false;try{store.session("editor-test");}catch(IllegalArgumentException expected){removed=true;}
            check(removed&&store.details("editor-test",false).isEmpty(),"Session delete retained data");
            boolean connectedBlocked=false;try{store.deleteSession("A");}catch(IllegalStateException expected){connectedBlocked=true;}
            check(connectedBlocked&&store.session("A")!=null,"Connected session deletion was not blocked");
            check(Catalog.names(source,"machine","スロット",null,false).contains("混合入力機種"),"Slot machine missing from category");
            check(!Catalog.names(source,"machine","パチンコ",null,false).contains("混合入力機種"),"Slot machine leaked into pachinko category");
            String recentDate=java.time.LocalDate.now().minusDays(1).toString();
            String oldDate=java.time.LocalDate.now().minusYears(5).toString();
            for(String[] item:new String[][]{{"old-candidate",oldDate,"旧ホール","旧機種"},{"new-candidate",recentDate,"最近ホール","最近機種"}})
                source.save(new JSONObject().put("id",item[0]).put("date",item[1]).put("hall",item[2])
                    .put("kind","スロット").put("machine",item[3]).put("investment_yen",0)
                    .put("recovery_yen",0).put("profit_yen",0).put("tag_ids",new JSONArray()));
            List<String> halls=Catalog.names(source,"hall"),machines=Catalog.names(source,"machine","スロット",null,false);
            check(halls.indexOf("最近ホール")<halls.indexOf("旧ホール")&&machines.indexOf("最近機種")<machines.indexOf("旧機種"),"Recent history was not prioritized");
            List<UnifiedLedger.Row> combined=new ArrayList<>();
            for(UnifiedLedger.Row row:UnifiedLedger.rows(source))if("mixed".equals(row.id)||"legacy".equals(row.id))combined.add(row);
            check(combined.size()==2&&UnifiedLedger.summary(combined).profit.equals(java.math.BigInteger.valueOf(-2000)),
                "Imported and new records did not share a total");
            String combinedCsv=ExportBundle.csv(UnifiedLedger.export(UnifiedLedger.rows(source),TagPicker.names(source)),"id","date","profit_yen","status","source_format","tag_names");
            check(combinedCsv.contains("\"mixed\"")&&combinedCsv.contains("\"legacy\"")
                &&combinedCsv.contains("\"session\"")&&combinedCsv.contains("\"record\"")
                &&combinedCsv.contains("朝一,特日"),"Combined CSV omitted a record source or tag name");
            CalendarEventStore events=new CalendarEventStore(source);
            JSONObject once=new JSONObject().put("hall","A店").put("title","取材")
                .put("rule",CalendarEventStore.ONCE).put("event_date","2026-10-18").put("starts_on","2026-10-18");
            events.save(once);
            JSONObject weekly=new JSONObject().put("hall","B店").put("title","月曜イベント")
                .put("rule",CalendarEventStore.WEEKLY).put("weekday",1).put("starts_on","2026-10-18");
            events.save(weekly);
            JSONObject monthly=new JSONObject().put("hall","C店").put("title","月末")
                .put("rule",CalendarEventStore.MONTHLY_DAY).put("day_of_month",31).put("starts_on","2026-10-01");
            events.save(monthly);
            JSONObject dd=new JSONObject().put("hall","D店").put("title","ゾロ目")
                .put("rule",CalendarEventStore.MONTHLY_DD).put("starts_on","2026-10-01")
                .put("ends_on","2026-10-31");
            events.save(dd);
            JSONObject persistedWeekly=null,persistedMonthly=null;
            for(JSONObject event:events.list()){
                if(CalendarEventStore.WEEKLY.equals(event.optString("rule")))persistedWeekly=event;
                if(CalendarEventStore.MONTHLY_DAY.equals(event.optString("rule")))persistedMonthly=event;
            }
            check(persistedWeekly!=null&&CalendarEventStore.occurs(persistedWeekly,java.time.LocalDate.parse("2026-10-19"))
                &&persistedMonthly!=null&&CalendarEventStore.occurs(persistedMonthly,java.time.LocalDate.parse("2026-10-31")),
                "Saved rules with an open end date did not display");
            check(CalendarEventStore.occurs(once,java.time.LocalDate.parse("2026-10-18"))
                &&!CalendarEventStore.occurs(once,java.time.LocalDate.parse("2026-10-19")),"One-off event recurrence failed");
            check(CalendarEventStore.occurs(weekly,java.time.LocalDate.parse("2026-10-19"))
                &&!CalendarEventStore.occurs(weekly,java.time.LocalDate.parse("2026-10-12")),"Weekly event start boundary failed");
            check(CalendarEventStore.occurs(monthly,java.time.LocalDate.parse("2026-10-31"))
                &&!CalendarEventStore.occurs(monthly,java.time.LocalDate.parse("2026-11-30")),"Monthly 31st rule failed");
            check(CalendarEventStore.occurs(dd,java.time.LocalDate.parse("2026-10-11"))
                &&CalendarEventStore.occurs(dd,java.time.LocalDate.parse("2026-10-22"))
                &&!CalendarEventStore.occurs(dd,java.time.LocalDate.parse("2026-11-11")),"Monthly DD boundaries failed");
            CounterStore counters=new CounterStore(source);
            counters.add("session","A","ベル");
            String counterId=counters.list("session","A").getJSONObject(0).getString("id");
            counters.increment(counterId);counters.increment(counterId);
            new CounterStore(source).undo(counterId);
            check(new CounterStore(source).list("session","A").getJSONObject(0).getLong("count")==1,
                "Counter did not resume and undo after reopening store");
            counters.increment(counterId);
            byte[] generic=("日付,投資,回収,ホール,機種,台番号,タグ,メモ\n"+
                "2026/10/15,10,1500,CSV店,試験機,001,朝一|狙い,\"改行\nメモ\"\n").getBytes(StandardCharsets.UTF_8);
            GenericCsv csv=new GenericCsv(generic);int[] mapping={0,1,2,3,4,5,6,7,-1,-1,-1};
            JSONObject converted=csv.convert(mapping,new HashMap<>());
            check(source.importCsv(converted)==1 && source.importCsv(converted)==1,"CSV import was not repeatable");
            JSONObject csvRow=converted.getJSONArray("records").getJSONObject(0);
            check("未分類".equals(csvRow.getString("kind"))&&"001".equals(csvRow.getString("machine_number"))
                &&csvRow.getString("memo").contains("\n"),"CSV mapping guessed or lost source values");
            String pRecordHeader="日付,店舗コード,店舗,メーカー,機種コード,機種,台番号,投資額,回収額,収支,メモ,稼働時間,時給\r\n";
            GenericCsv pRecord=new GenericCsv((pRecordHeader+
                "2026/10/19,10,公式例店,メーカー,20,公式例機,009,1000,2500,+1500,\"改行\nメモ\",120.0,750.0\r\n")
                .getBytes(StandardCharsets.UTF_8));
            check(pRecord.matchesPRecordSample(),"Official pRecord sample header not recognized");
            int[] pMap=new int[GenericCsv.FIELDS.length];
            for(int i=0;i<pMap.length;i++)pMap[i]=pRecord.suggested(i);
            JSONObject pConverted=pRecord.convert(pMap,new HashMap<>());
            check(pConverted.getJSONArray("records").getJSONObject(0).getLong("profit_yen")==1500
                &&new JSONObject(pConverted.getJSONArray("record_details").getJSONObject(0).getString("payload"))
                    .getLong("duration_minutes")==120,
                "Official pRecord sample conversion failed");
            source.importCsv(pConverted);
            String tsv="遊技日\t投資金額\t回収金額\t店舗名\t機種名\t種別\tメモ\n"
                +"2026-10-20\t1000\t2000\t試験店\t試験機\tパチスロ\t旧端末\n";
            GenericCsv ms932=new GenericCsv(tsv.getBytes(java.nio.charset.Charset.forName("Windows-31J")),
                java.nio.charset.Charset.forName("Windows-31J"));
            int[] tMap=new int[GenericCsv.FIELDS.length];
            for(int i=0;i<tMap.length;i++)tMap[i]=ms932.suggested(i);
            JSONObject tConverted=ms932.convert(tMap,new HashMap<>());
            check(ms932.delimiter=='\t'&&"スロット".equals(tConverted.getJSONArray("records")
                .getJSONObject(0).getString("kind")),"MS932 TSV or game type mapping failed");
            source.importCsv(tConverted);
            GenericCsv pachiEvCsv=new GenericCsv(("date,machine,store,investment,return,profit,memo\r\n"
                +"2026-10-14,公開実装機種,公開実装店,1200,3400,2200,CSV記録\r\n")
                .getBytes(StandardCharsets.UTF_8));
            check(pachiEvCsv.matchesPachiEvCsv(),"Published pachi-ev CSV header not recognized");
            int[] evMap=new int[GenericCsv.FIELDS.length];
            for(int i=0;i<evMap.length;i++)evMap[i]=pachiEvCsv.suggested(i);
            JSONObject evCsvConverted=pachiEvCsv.convert(evMap,new HashMap<>());
            check(evCsvConverted.getJSONArray("records").getJSONObject(0).getLong("profit_yen")==2200,
                "Published pachi-ev CSV was not mapped");
            source.importCsv(evCsvConverted);
            JSONObject evOriginal=new JSONObject().put("id","published-example-1")
                .put("date","2026-10-13").put("machine","公開実装機種")
                .put("hall","公開実装店").put("investment",1000).put("recovery",3000)
                .put("unitDiff",120).put("type","枚").put("memo","JSON記録");
            JSONObject evInput=new JSONObject().put("records",new JSONArray().put(evOriginal))
                .put("settings",new JSONObject().put("bankroll",100000));
            JSONObject evJsonConverted=PachiEvJson.convert(evInput);
            JSONObject evRow=evJsonConverted.getJSONArray("records").getJSONObject(0);
            String evId=evRow.getString("id");
            check("スロット".equals(evRow.getString("kind"))
                &&new JSONObject(evJsonConverted.getJSONArray("record_details").getJSONObject(0)
                    .getString("payload")).getJSONObject("source_original").getInt("unitDiff")==120,
                "Published pachi-ev JSON fields were not preserved");
            check(source.importCsv(evJsonConverted)==1&&source.importCsv(evJsonConverted)==1,
                "pachi-ev JSON import was not repeatable");
            check(source.recordDetails(evId).getJSONObject("source_original").getInt("unitDiff")==120,
                "pachi-ev source units disappeared after import");
            String evBefore=source.backup().toString();
            JSONObject evConflict=new JSONObject(evJsonConverted.toString());
            evConflict.getJSONArray("records").getJSONObject(0).put("memo","同じIDで異なる内容");
            boolean evRejected=false;
            try{source.importCsv(evConflict);}catch(IllegalStateException expected){evRejected=true;}
            check(evRejected&&evBefore.equals(source.backup().toString()),
                "pachi-ev JSON conflict partially changed the database");
            boolean duplicateEvRejected=false;
            try{PachiEvJson.convert(new JSONObject().put("settings",new JSONObject())
                .put("records",new JSONArray().put(evOriginal).put(new JSONObject(evOriginal.toString()))));}
            catch(IllegalArgumentException expected){duplicateEvRejected=true;}
            check(duplicateEvRejected&&evBefore.equals(source.backup().toString()),
                "Duplicate pachi-ev source ID changed the database");
            android.database.sqlite.SQLiteDatabase exporting=source.getWritableDatabase();exporting.beginTransaction();
            try{
                JSONObject consistent=source.backup();
                check(consistent.getJSONArray("records").length()>0&&UnifiedLedger.rows(source).size()>0,
                    "Combined snapshot could not be read atomically");
                exporting.setTransactionSuccessful();
            }finally{exporting.endTransaction();}
            JSONObject before=source.backup();
            String clean=before.toString();
            JSONObject changedCsv=new JSONObject(converted.toString());
            changedCsv.getJSONArray("tags").put(new JSONObject().put("source_id","csv-new-tag")
                .put("name","衝突後のタグ").put("type","").put("priority",""));
            changedCsv.getJSONArray("records").getJSONObject(0).put("memo","衝突する変更");
            boolean csvConflict=false;
            try{source.importCsv(changedCsv);}catch(IllegalStateException expected){csvConflict=true;}
            check(csvConflict&&clean.equals(source.backup().toString()),"CSV conflict partially changed data");
            JSONObject orphan=new JSONObject(clean);
            orphan.getJSONArray("counters").put(new JSONObject().put("id","orphan-counter")
                .put("owner_type","session").put("owner_id","missing-session")
                .put("name","不正").put("count",1).put("undo_available",0).put("updated_at",1));
            boolean orphanFailed=false;
            try{source.importJson(orphan);}catch(IllegalArgumentException expected){orphanFailed=true;}
            check(orphanFailed&&clean.equals(source.backup().toString()),"Orphan counter partially changed data");
            JSONObject duplicate=new JSONObject(clean);
            duplicate.getJSONArray("records").put(new JSONObject(duplicate.getJSONArray("records").getJSONObject(0).toString()));
            boolean duplicateFailed=false;
            try{source.importJson(duplicate);}catch(JSONException expected){duplicateFailed=true;}
            check(duplicateFailed&&clean.equals(source.backup().toString()),"Duplicate ID changed the database");
            boolean corruptFailed=false;
            try{BackupIO.readJson(new ByteArrayInputStream("{broken".getBytes(StandardCharsets.UTF_8)));}
            catch(Exception expected){corruptFailed=true;}
            check(corruptFailed&&clean.equals(source.backup().toString()),"Corrupt JSON changed the database");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream(); ExportBundle.write(before,bytes,UnifiedLedger.export(UnifiedLedger.rows(source)));
            JSONObject fromZip=BackupIO.readZip(new ByteArrayInputStream(bytes.toByteArray()),context.getCacheDir());
            check(before.toString().equals(fromZip.toString()),"ZIP backup.json changed during reading");
            boolean truncatedFailed=false;
            try{BackupIO.readZip(new ByteArrayInputStream(Arrays.copyOf(bytes.toByteArray(),bytes.size()/2)),context.getCacheDir());}
            catch(Exception expected){truncatedFailed=true;}
            check(truncatedFailed&&clean.equals(source.backup().toString()),"Truncated ZIP changed the database");
            JSONObject fromJson=BackupIO.readJson(new ByteArrayInputStream(before.toString().getBytes(StandardCharsets.UTF_8)));
            check(before.toString().equals(fromJson.toString())&&BackupIO.preview(fromJson).contains("期間"),
                "JSON preview or read failed");
            Map<String,byte[]> entries=new LinkedHashMap<>();
            try(ZipInputStream zip=new ZipInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
                ZipEntry entry; byte[] buffer=new byte[8192];
                while((entry=zip.getNextEntry())!=null) {
                    ByteArrayOutputStream value=new ByteArrayOutputStream(); int count;
                    while((count=zip.read(buffer))!=-1) value.write(buffer,0,count);
                    entries.put(entry.getName(),value.toByteArray());
                }
            }
            check(entries.containsKey("sessions.csv")&&entries.containsKey("record_tags.csv")&&entries.containsKey("all_records.csv")
                &&entries.containsKey("calendar_events.csv")&&entries.containsKey("counters.csv"),"CSV tables missing");
            check(new String(entries.get("tags.csv"),StandardCharsets.UTF_8).contains("朝一,特日\n🎰\"\"試験\"\""),"CSV escaping lost");
            check(Arrays.equals(pcb,entries.get("sources/0/original.pcb")),"PCB bytes changed");
            check(new String(entries.get("sources/0/raw_entries.csv"),StandardCharsets.UTF_8).contains("unknown_setting"),"Unknown field missing");
            JSONObject exported=new JSONObject(new String(entries.get("backup.json"),StandardCharsets.UTF_8));
            restored.importJson(fromZip);
            check(before.toString().equals(restored.backup().toString()),"Round trip mismatch");
            String jsonName="verification-json.db";context.deleteDatabase(jsonName);
            try(LedgerDb jsonRestored=new LedgerDb(context,jsonName)){
                jsonRestored.importJson(fromJson);
                check(before.toString().equals(jsonRestored.backup().toString()),"JSON empty database round trip mismatch");
            }finally{context.deleteDatabase(jsonName);}
            check(new CounterStore(restored).list("session","A").getJSONObject(0).getLong("count")==2,
                "Restored counter value differs");
            String oldName="verification-v7.db";context.deleteDatabase(oldName);
            try(LedgerDb oldRestored=new LedgerDb(context,oldName)){
                JSONObject v7=new JSONObject(before.toString());v7.put("format","pachibo-ledger-v7");v7.remove("counters");
                oldRestored.importJson(v7);
                check(oldRestored.backup().getJSONArray("records").length()==before.getJSONArray("records").length()
                    &&oldRestored.backup().getJSONArray("calendar_events").length()==before.getJSONArray("calendar_events").length()
                    &&oldRestored.backup().getJSONArray("counters").length()==0,"v7 backup compatibility failed");
            }finally{context.deleteDatabase(oldName);}
            check(new CalendarEventStore(restored).list().size()==4,"Calendar events not restored");
            restored.importJson(exported);
            check(before.toString().equals(restored.backup().toString()),"Duplicate import changed data");
            check(entries.containsKey("edit_history.csv")&&entries.containsKey("accounts.csv"),"History or account CSV missing");
            SessionStore restoredStore=new SessionStore(restored);
            String transferEdit=null;
            for(JSONObject edit:restoredStore.history("B")) if("transfers".equals(edit.getString("entity_type"))) { transferEdit=edit.getString("id"); break; }
            check(transferEdit!=null,"Restored history missing");
            restoredStore.undo(transferEdit);
            check(restoredStore.calculate(Collections.singleton("A")).evaluated==null,"Restored transfer undo failed");
            check(restoredStore.calculate(new HashSet<>(Arrays.asList("A","B"))).evaluated.roundYen().equals(java.math.BigInteger.valueOf(6000)),"Restored undo changed combined result");
            restoredStore.undo(restoredStore.history("B").get(0).getString("id"));
            check(new SessionStore(restored).calculate(new HashSet<>(Arrays.asList("A","B"))).evaluated.roundYen().equals(java.math.BigInteger.valueOf(6000)),"Transfer result changed");
            new SessionStore(restored).saveMetadata("A",new JSONObject(meta.toString()).put("memo","ユーザー訂正"));
            String edited=restored.backup().toString(); boolean rejected=false;
            try { restored.importJson(exported); } catch(IllegalStateException expected) { rejected=true; }
            check(rejected,"Edited record overwritten");
            check(edited.equals(restored.backup().toString()),"Failed import was not atomic");
            try(OutputStream file=context.openFileOutput("verification-complete.zip",Context.MODE_PRIVATE)) { file.write(bytes.toByteArray()); }
            result.putString("stream","ROUNDTRIP_PASS: v8 JSON/ZIP empty-DB restoration, v7 backup compatibility, duplicate/corrupt rejection, generic CSV mapping, counter save/undo/restore, mixed cash/medal finish, tags, calendar events, exchange rates, calculation details, PCB preservation and conflict rollback\n");
            finish(-1,result);
        } catch(Throwable error) {
            result.putString("stream","ROUNDTRIP_FAIL: "+android.util.Log.getStackTraceString(error)); finish(0,result);
        } finally { context.deleteDatabase(nameA); context.deleteDatabase(nameB); }
    }
    private static void verifyAnalysisMetrics(Context context) throws Exception {
        String name="verification-analysis.db";context.deleteDatabase(name);
        try(LedgerDb metrics=new LedgerDb(context,name)){
            JSONObject first=new JSONObject().put("id","metric-1").put("date","2026-10-20")
                .put("hall","A").put("kind","スロット").put("machine","M")
                .put("investment_yen",10000).put("recovery_yen",16000).put("profit_yen",6000);
            metrics.saveRecord(first,new JSONObject().put("spins",500).put("work_yen",7500));
            JSONObject second=new JSONObject(first.toString()).put("id","metric-2")
                .put("investment_yen",5000).put("recovery_yen",0).put("profit_yen",-5000);
            metrics.saveRecord(second,new JSONObject().put("spins",200));
            JSONObject expense=new JSONObject(first.toString()).put("id","metric-expense")
                .put("date","2026-10-21").put("investment_yen",1000)
                .put("recovery_yen",0).put("profit_yen",-1000);
            metrics.saveRecord(expense,new JSONObject().put("expense",true));
            AnalysisMetrics.Stats stats=AnalysisMetrics.calculate(UnifiedLedger.rows(metrics));
            check(stats.playCount==2&&stats.expenseCount==1&&stats.winningDays==1&&stats.days.size()==2,
                "Daily win aggregation failed");
            check(stats.investment.equals(java.math.BigInteger.valueOf(15000))&&
                stats.recovery.equals(java.math.BigInteger.valueOf(16000))&&stats.flowCount==2,
                "Investment/recovery totals included expense or dropped a play");
            check(stats.spins==700&&stats.workSpins==500&&
                stats.matchedWorkYen.equals(java.math.BigInteger.valueOf(7500)),
                "Work per spin included a row without paired data");
            SessionStore store=new SessionStore(metrics);
            String today=java.time.LocalDate.now().toString();
            long began=java.time.LocalDate.now().atTime(10,0)
                .atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
            store.startAt("metric-session",today,"test-account",new JSONObject()
                .put("hall","A").put("machine","M").put("game_kind","スロット")
                .put("time_recorded",false),began);
            store.finishWithAmountsAt("metric-session","metric-finish",10000,0,16000,0,
                null,null,"",new JSONArray(),began+3600000);
            UnifiedLedger.Row hidden=null;
            for(UnifiedLedger.Row row:UnifiedLedger.rows(metrics))if("metric-session".equals(row.id))hidden=row;
            check(hidden!=null&&hidden.durationMinutes==null&&
                hidden.investment.equals(java.math.BigInteger.valueOf(10000))&&
                hidden.recovery.equals(java.math.BigInteger.valueOf(16000)),
                "Hidden times or session flow accounting failed");
        }finally{context.deleteDatabase(name);}
    }

    private void verifyRealPcb() {
        Bundle result=new Bundle(); Context context=getTargetContext();
        String nameA="verification-real-source.db",nameB="verification-real-restore.db";
        context.deleteDatabase(nameA); context.deleteDatabase(nameB);
        try(LedgerDb source=new LedgerDb(context,nameA); LedgerDb restored=new LedgerDb(context,nameB)) {
            long start=android.os.SystemClock.elapsedRealtime();
            JSONObject audit;
            try(InputStream input=context.openFileInput("verification-input.pcb")) {
                JSONObject imported=PcbReader.parse(input); audit=imported.getJSONObject("audit");
                audit.put("raw_entries",imported.getJSONArray("raw_entries").length());
                audit.put("source_sha256",imported.getString("source_sha256"));
                source.importJson(imported);
            }
            List<UnifiedLedger.Row> all=UnifiedLedger.rows(source);
            UnifiedLedger.Summary amounts=UnifiedLedger.summary(all);
            AnalysisMetrics.Stats metrics=AnalysisMetrics.calculate(all);
            int unclassified=0;for(UnifiedLedger.Row row:all)if("未分類".equals(row.kind))unclassified++;
            check(amounts.count==3794&&amounts.review==42&&unclassified==14
                &&audit.getInt("game_kind_from_historical_rate")==1450,
                "Real PCB classification or included profit count changed");
            check(metrics.playCount==3791&&metrics.expenseCount==3&&metrics.knownTimeCount==3594
                &&metrics.total().equals(java.math.BigInteger.valueOf(5152697)),
                "Real PCB expense or imported time analysis changed");
            audit.put("expense_records",metrics.expenseCount);
            audit.put("timed_play_records",metrics.knownTimeCount);
            audit.put("all_in_profit_yen",metrics.total().toString());
            audit.put("unclassified_records",unclassified);
            audit.put("included_profit_records",amounts.count);
            audit.put("parse_import_ms",android.os.SystemClock.elapsedRealtime()-start);
            long exportedAt=android.os.SystemClock.elapsedRealtime();
            JSONObject snapshot=source.backup();
            audit.put("records",snapshot.getJSONArray("records").length());
            audit.put("tags",snapshot.getJSONArray("tags").length());
            try(OutputStream output=context.openFileOutput("verification-real-complete.zip",Context.MODE_PRIVATE)) { ExportBundle.write(snapshot,output); }
            audit.put("export_ms",android.os.SystemClock.elapsedRealtime()-exportedAt);
            long restoreAt=android.os.SystemClock.elapsedRealtime();
            restored.importJson(snapshot);
            JSONObject after=restored.backup();
            for(String table:new String[]{"records","tags","sessions","operations","transfers","source_archives","edit_history","accounts","catalog","record_details"})
                check(snapshot.getJSONArray(table).toString().equals(after.getJSONArray(table).toString()),"Real round trip mismatch: "+table);
            audit.put("restore_compare_ms",android.os.SystemClock.elapsedRealtime()-restoreAt);
            audit.put("all_tables_equal",true);
            try(OutputStream output=context.openFileOutput("verification-real-audit.json",Context.MODE_PRIVATE)) { output.write(audit.toString(2).getBytes(StandardCharsets.UTF_8)); }
            result.putString("stream","REAL_PCB_PASS "+audit.toString()+"\n"); finish(-1,result);
        } catch(Throwable error) {
            result.putString("stream","REAL_PCB_FAIL: "+android.util.Log.getStackTraceString(error)); finish(0,result);
        } finally { context.deleteDatabase(nameA); context.deleteDatabase(nameB); }
    }
}
