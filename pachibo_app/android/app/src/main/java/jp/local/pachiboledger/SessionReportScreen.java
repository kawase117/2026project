package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.widget.*;
import java.math.BigInteger;
import java.time.LocalDate;
import java.util.*;
import java.util.function.Consumer;

/** Analysis across both storage formats, with drilldown to source records. */
final class SessionReportScreen {
    private final Activity activity;
    private final LedgerDb db;
    private final Consumer<LocalDate> openDay;
    private final Consumer<UnifiedLedger.Row> openRow;
    SessionReportScreen(Activity activity,LedgerDb db,Consumer<LocalDate> openDay,
                        Consumer<UnifiedLedger.Row> openRow){
        this.activity=activity;this.db=db;this.openDay=openDay;this.openRow=openRow;
    }
    private TextView text(String value,int size){
        TextView view=new TextView(activity);view.setText(value);view.setTextSize(size);
        view.setPadding(8,10,8,10);view.setTextColor(FormUi.INK);return view;
    }
    private Button button(String title,Runnable action){
        Button view=new Button(activity);FormUi.styleButton(view);view.setText(title);
        view.setOnClickListener(v->action.run());return view;
    }
    void render(LinearLayout root){
        root.addView(text("直近の成績を既定表示します。収支は事実の集計で、将来の勝ちを保証しません。",14));
        EditText from=FormUi.date(activity,root,"開始日",LocalDate.now().minusDays(89).toString(),true);
        EditText to=FormUi.date(activity,root,"終了日",LocalDate.now().toString(),true);
        LinearLayout presets=new LinearLayout(activity);root.addView(presets);
        FormUi.label(activity,root,"遊技種別");
        Spinner game=new Spinner(activity);game.setContentDescription("遊技種別");
        game.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,
            new String[]{"すべて","スロット","パチンコ","未分類","経費"}));root.addView(game);
        EditText hall=FormUi.choice(activity,db,root,"ホール","","hall",true);
        EditText machine=FormUi.choice(activity,db,root,"機種","","machine",true,
            ()->{String chosen=game.getSelectedItem().toString();return "スロット".equals(chosen)||"パチンコ".equals(chosen)?chosen:null;},
            ()->hall.getText().toString().trim());
        Set<String> tags=new LinkedHashSet<>();
        TextView tagLabel=text("タグ条件：指定なし",14);root.addView(tagLabel);
        root.addView(button("絞り込むタグを選択",()->TagPicker.show(activity,db,tags,false,selected->{
            tags.clear();tags.addAll(selected);
            try{tagLabel.setText("タグ条件："+TagPicker.display(db,TagPicker.array(tags)));}
            catch(Exception error){showError(error);}
        })));
        CheckBox allTags=new CheckBox(activity);allTags.setText("選択タグをすべて含む（オフならいずれか）");
        allTags.setChecked(true);root.addView(allTags);
        Spinner range=new Spinner(activity);range.setContentDescription("グラフの上下幅");
        range.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,
            new String[]{"グラフ幅：自動","±3万円","±5万円","±10万円"}));root.addView(range);
        Spinner sort=new Spinner(activity);sort.setContentDescription("比較表の並び順");
        sort.setAdapter(new ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,
            new String[]{"比較：件数順","比較：収支順","比較：勝率順","比較：回収率順","比較：計算回転単価順"}));root.addView(sort);
        LinearLayout output=new LinearLayout(activity);output.setOrientation(1);
        Runnable update=()->{
            try{
                String start=from.getText().toString().trim(),end=to.getText().toString().trim();
                if(!start.isEmpty())LocalDate.parse(start);
                if(!end.isEmpty())LocalDate.parse(end);
                if(!start.isEmpty()&&!end.isEmpty()&&start.compareTo(end)>0)
                    throw new IllegalArgumentException("開始日を終了日以前にしてください");
                String hallName=hall.getText().toString().trim(),machineName=machine.getText().toString().trim();
                String selectedGame=game.getSelectedItem().toString();
                List<UnifiedLedger.Row> chosen=new ArrayList<>();
                for(UnifiedLedger.Row row:UnifiedLedger.rows(db)){
                    if(!start.isEmpty()&&row.date.compareTo(start)<0||!end.isEmpty()&&row.date.compareTo(end)>0)continue;
                    if("経費".equals(selectedGame)!=row.expense && !"すべて".equals(selectedGame))continue;
                    if(!"すべて".equals(selectedGame)&&!"経費".equals(selectedGame)&&!selectedGame.equals(row.kind))continue;
                    if(!hallName.isEmpty()&&!hallName.equals(row.expense&&!row.expenseHall.isEmpty()?row.expenseHall:row.hall))continue;
                    if(!machineName.isEmpty()&&!machineName.equals(row.expense&&!row.expenseMachine.isEmpty()?row.expenseMachine:row.machine))continue;
                    if(!TagFilter.matches(TagPicker.ids(row.tags),tags,allTags.isChecked()))continue;
                    chosen.add(row);
                }
                output.removeAllViews();renderResult(output,chosen,start,end,
                    new long[]{0,30000,50000,100000}[range.getSelectedItemPosition()],sort.getSelectedItemPosition());
            }catch(Exception error){showError(error);}
        };
        for(String period:new String[]{"30日","90日","今年","全期間"})
            presets.addView(button(period,()->{
                LocalDate today=LocalDate.now();
                from.setText("全期間".equals(period)?"":"今年".equals(period)?today.withDayOfYear(1).toString():
                    today.minusDays("30日".equals(period)?29:89).toString());
                to.setText("全期間".equals(period)?"":today.toString());update.run();
            }),new LinearLayout.LayoutParams(0,-2,1));
        root.addView(button("集計する",update));root.addView(output);update.run();
    }

    private void renderResult(LinearLayout output,List<UnifiedLedger.Row> selected,String from,String to,
                              long chartRange,int sortMode)throws Exception{
        UnifiedLedger.Summary count=UnifiedLedger.summary(selected);
        List<UnifiedLedger.Row> complete=new ArrayList<>();
        for(UnifiedLedger.Row row:selected)if(row.profit!=null)complete.add(row);
        AnalysisMetrics.Stats stats=AnalysisMetrics.calculate(complete);
        output.addView(text("期間："+(from.isEmpty()?"最初の記録":from)+" ～ "+(to.isEmpty()?"最新":to),14));
        output.addView(text("対象 "+selected.size()+"件 / 実収支に計上 "+complete.size()+"件 / 除外 "+
            (selected.size()-complete.size())+"件",15));
        if(stats.playCount>0&&stats.playCount<10)output.addView(text("遊技が10件未満です。平均・勝率・比較結果は少数例として見てください。",14));
        if(chartRange>0)output.addView(text("グラフ幅：±"+String.format(Locale.JAPAN,"%,d円",chartRange)+
            "。値が範囲を超える場合は自動で拡張します。",13));
        output.addView(text("経費込みの収支  "+FormUi.money(stats.total()),21));
        output.addView(text("遊技 "+stats.playCount+"件  "+FormUi.money(stats.playProfit)+
            "\n経費 "+stats.expenseCount+"件  "+FormUi.money(stats.expenseProfit),17));
        output.addView(text("遊技中 "+count.active+"件 ／ 要確認 "+count.review+
            "件 ／ 計算待ち "+count.unvalued+"件（いずれも収支から除外）",13));
        if(complete.isEmpty()){output.addView(text("条件に合う確定収支はありません",16));return;}
        if(stats.playCount>0){
            output.addView(text(String.format(Locale.JAPAN,
                "一台ごとの勝率 %.1f%%（%d/%d件） ／ 中央値 %s",
                stats.winningPlays*100.0/stats.playCount,stats.winningPlays,stats.playCount,
                FormUi.money(stats.medianPlay)),15));
            output.addView(text(String.format(Locale.JAPAN,
                "確定収支のある日の勝率 %.1f%%（%d/%d日） ／ 日別中央値 %s",
                stats.days.isEmpty()?0:stats.winningDays*100.0/stats.days.size(),stats.winningDays,
                stats.days.size(),FormUi.money(stats.medianDay)),15));
            output.addView(text("日別はその日の遊技と経費を合算し、経費だけの日も含めます。",13));
            output.addView(text("回収率 "+recoveryRate(stats)+"（回収額÷投資額）"+
                " ／ 投資・回収が分かる遊技 "+stats.flowCount+"/"+stats.playCount+
                "件。台移動の持ち玉は投資・回収に重複計上しません。台移動を含む機種別の回収率は参考値です。",15));
            if(stats.spinCount>0)output.addView(text("回転数の記録 "+stats.spinCount+"/"+stats.playCount+
                "件 ／ 合計 "+String.format(Locale.JAPAN,"%,d回転",stats.spins),15));
            if(stats.formulaCount>0)output.addView(text("4円パチンコの計算仕事量 "+FormUi.money(stats.formulaWorkYen)+
                " ／ "+stats.formulaCount+"/"+stats.playCount+"件"+(stats.formulaSpins>0?
                String.format(Locale.JAPAN," ／ 加重回転単価 %.2f円/回転（計算仕事量÷通常回転数）",
                    stats.formulaWorkYen.doubleValue()/stats.formulaSpins):""),15));
            if(stats.manualWorkCount>0)output.addView(text("手入力の仕事量 "+FormUi.money(
                stats.workYen.subtract(stats.formulaWorkYen))+" ／ "+stats.manualWorkCount+"件",15));
            if(stats.workCount>0)output.addView(text("仕事量は期待値の記録で、実収支とは別です。計算値は4円パチンコの等価ボーダー・回転率・持ち玉比率・交換率から求めています。",13));
        }
        output.addView(text("日別累積収支の最大落ち込み  "+FormUi.money(stats.maxDrawdown.negate())+
            "（直前の最高値からの下落）",15));
        if(stats.knownMinutes>0){
            output.addView(text("時間当たり収支  "+FormUi.money(stats.hourly())+
                " ／ 時間記録あり "+stats.knownTimeCount+"/"+stats.playCount+"件（計 "+
                timeText(stats.knownMinutes)+"）"+
                (stats.knownMinutes<60?" ／ 1時間未満・参考値":""),15));
        }else output.addView(text("時間当たり収支：開始・終了時刻のある遊技記録がありません",14));
        output.addView(text("時間当たり収支は時刻のある遊技だけで計算し、経費は含めません。過去の時刻は同じ .pcb を再取込すると補完されます。",13));
        SortedMap<String,Double> cumulative=new TreeMap<>();BigInteger running=BigInteger.ZERO;
        for(Map.Entry<String,BigInteger> day:stats.days.entrySet()){
            running=running.add(day.getValue());cumulative.put(day.getKey(),running.doubleValue());
        }
        SortedMap<String,Double> daily=new TreeMap<>();
        for(Map.Entry<String,BigInteger> day:stats.days.entrySet())daily.put(day.getKey(),day.getValue().doubleValue());
        output.addView(text("日別損益：その日に確定した遊技と経費の合計。日ごとの増減です。",18));
        DateProfitChart dailyChart=new DateProfitChart(activity);dailyChart.setBars(true);
        dailyChart.setMinimumRangeYen(chartRange);dailyChart.setValues(daily);
        output.addView(dailyChart,new LinearLayout.LayoutParams(-1,FormUi.dp(activity,220)));
        output.addView(text("累積損益：日別損益を日付順に足した残高。実収支の推移です。",18));
        DateProfitChart line=new DateProfitChart(activity);line.setMinimumRangeYen(chartRange);line.setValues(cumulative);
        output.addView(line,new LinearLayout.LayoutParams(-1,FormUi.dp(activity,220)));
        output.addView(text("一台ごとの収支分布",18));
        DistributionChart distribution=new DistributionChart(activity);distribution.setCounts(stats.distribution);
        output.addView(distribution,new LinearLayout.LayoutParams(-1,FormUi.dp(activity,200)));
        addGroups(output,"月別収支",groups(complete,"month"),true,chartRange,sortMode);
        addGroups(output,"日別収支",groups(complete,"date"),false,chartRange,sortMode);
        addGroups(output,"曜日別",groups(complete,"weekday"),false,chartRange,sortMode);
        addGroups(output,"ホール別（経費は指定された対象ホールへ）",groups(complete,"hall"),false,chartRange,sortMode);
        addGroups(output,"機種別（経費は指定された対象機種へ）",groups(complete,"machine"),false,chartRange,sortMode);
        addGroups(output,"ホール×機種（記録10件未満は参考値）",groups(complete,"hall_machine"),false,chartRange,sortMode);
        Map<String,String> names=TagPicker.names(db);
        SortedMap<String,List<UnifiedLedger.Row>> tagGroups=new TreeMap<>();
        for(UnifiedLedger.Row row:complete){
            Set<String> ids=TagPicker.ids(row.tags);
            if(ids.isEmpty())tagGroups.computeIfAbsent("タグなし",key->new ArrayList<>()).add(row);
            for(String id:ids)tagGroups.computeIfAbsent(names.getOrDefault(id,id),key->new ArrayList<>()).add(row);
        }
        output.addView(text("タグ別：複数タグの記録は各タグに現れるため、行の合計は全体と一致しません。タグの成績は記録時の選択にも左右されます。",13));
        addGroups(output,"タグ別",tagGroups,false,chartRange,sortMode);
    }

    private static SortedMap<String,List<UnifiedLedger.Row>> groups(List<UnifiedLedger.Row> rows,String axis){
        SortedMap<String,List<UnifiedLedger.Row>> result=new TreeMap<>();
        for(UnifiedLedger.Row row:rows){
            String hall=row.expense?(row.expenseHall.isEmpty()?"割当先なし（経費）":row.expenseHall):row.hall;
            String machine=row.expense?(row.expenseMachine.isEmpty()?"割当先なし（経費）":row.expenseMachine):row.machine;
            String key="date".equals(axis)?row.date:"month".equals(axis)?row.date.substring(0,7):
                "weekday".equals(axis)?weekday(row.date):
                "hall".equals(axis)?hall:"machine".equals(axis)?machine:hall+" ／ "+machine;
            result.computeIfAbsent(key,value->new ArrayList<>()).add(row);
        }
        return result;
    }
    private static String weekday(String day){
        int index=LocalDate.parse(day).getDayOfWeek().getValue()-1;
        return new String[]{"月曜日","火曜日","水曜日","木曜日","金曜日","土曜日","日曜日"}[index];
    }
    private static String recoveryRate(AnalysisMetrics.Stats stats){
        if(stats.investment.signum()==0)return "算出不可（投資額0円）";
        return String.format(Locale.JAPAN,"%.1f%%",stats.recovery.doubleValue()*100.0/stats.investment.doubleValue());
    }

    private static boolean showGroupTime(String heading){
        return "月別収支".equals(heading)||heading.startsWith("ホール別")||heading.startsWith("機種別");
    }

    private static String timeText(long minutes){
        if(minutes<60)return minutes+"分";
        long hours=minutes/60,remainder=minutes%60;
        return String.format(Locale.JAPAN,"%,d時間",hours)+(remainder==0?"":remainder+"分");
    }

    private static String groupTime(AnalysisMetrics.Stats stats){
        if(stats.playCount==0)return "";
        String coverage="時間記録あり "+stats.knownTimeCount+"/"+stats.playCount+"件";
        if(stats.knownMinutes==0)return "\n遊技時間：記録なし（"+coverage+"）";
        return "\n記録された遊技時間 "+timeText(stats.knownMinutes)+
            " ／ "+coverage+" ／ 時間当たり "+FormUi.money(stats.hourly())+
            (stats.knownMinutes<60?"（1時間未満・参考値）":"");
    }

    private void addGroups(LinearLayout output,String heading,SortedMap<String,List<UnifiedLedger.Row>> grouped,
                           boolean chart,long chartRange,int sortMode){
        output.addView(text(heading,18));
        if(chart){
            SortedMap<String,Double> values=new TreeMap<>();
            for(Map.Entry<String,List<UnifiedLedger.Row>> group:grouped.entrySet())
                values.put(group.getKey()+"-01",AnalysisMetrics.calculate(group.getValue()).total().doubleValue());
            DateProfitChart bars=new DateProfitChart(activity);bars.setBars(true);
            bars.setMinimumRangeYen(chartRange);bars.setValues(values);
            output.addView(bars,new LinearLayout.LayoutParams(-1,FormUi.dp(activity,180)));
        }
        List<Map.Entry<String,List<UnifiedLedger.Row>>> ranked=new ArrayList<>(grouped.entrySet());
        if("日別収支".equals(heading)||"月別収支".equals(heading))
            ranked.sort((a,b)->b.getKey().compareTo(a.getKey()));
        else if("曜日別".equals(heading)){
            List<String> order=Arrays.asList("月曜日","火曜日","水曜日","木曜日","金曜日","土曜日","日曜日");
            ranked.sort(Comparator.comparingInt(entry->order.indexOf(entry.getKey())));
        }
        else if(!"曜日別".equals(heading)){
            Map<String,AnalysisMetrics.Stats> summaries=new HashMap<>();
            for(Map.Entry<String,List<UnifiedLedger.Row>> entry:ranked)
                summaries.put(entry.getKey(),AnalysisMetrics.calculate(entry.getValue()));
            ranked.sort((a,b)->{
                AnalysisMetrics.Stats x=summaries.get(a.getKey()),y=summaries.get(b.getKey());
                int order=sortMode==1?y.total().compareTo(x.total()):sortMode==2?
                    Double.compare(winRate(y),winRate(x)):sortMode==3?
                    Double.compare(rateNumber(y),rateNumber(x)):sortMode==4?
                    Double.compare(formulaUnit(y),formulaUnit(x)):
                    Integer.compare(y.playCount,x.playCount);
                return order!=0?order:a.getKey().compareTo(b.getKey());
            });
        }
        int shown=0;
        for(Map.Entry<String,List<UnifiedLedger.Row>> entry:ranked){
            if(shown++==30){output.addView(text("残り "+(ranked.size()-30)+"組。期間や条件を絞ってください。",13));break;}
            AnalysisMetrics.Stats stats=AnalysisMetrics.calculate(entry.getValue());
            String caution=stats.playCount==0?"経費のみ":stats.playCount<10?" ／ 少数件・参考値":"";
            String label=entry.getKey()+" ／ 遊技 "+stats.playCount+"件・"+stats.playDates.size()+"日"+
                (stats.expenseCount>0?"・経費 "+stats.expenseCount+"件":"")+
                " ／ "+FormUi.money(stats.total())+
                (stats.playCount>0?String.format(Locale.JAPAN," ／ 勝率 %.0f%%",winRate(stats))+
                    " ／ 回収率 "+recoveryRate(stats)+
                    " ／ 中央値 "+FormUi.money(stats.medianPlay):"")+caution+
                (stats.formulaCount>0?"\n計算仕事量 "+FormUi.money(stats.formulaWorkYen)+" / "+stats.formulaCount+"件"+
                    (stats.formulaSpins>0?String.format(Locale.JAPAN," / %.2f円/回転",stats.formulaWorkYen.doubleValue()/stats.formulaSpins):""):"")+
                (stats.spinCount>0?" / 回転数 "+String.format(Locale.JAPAN,"%,d",stats.spins)+"（"+stats.spinCount+"件）":"")+
                (showGroupTime(heading)?groupTime(stats):"");
            output.addView(button(label,()->showRows(entry.getKey(),entry.getValue())));
        }
    }
    private static double winRate(AnalysisMetrics.Stats stats){
        return stats.playCount==0?Double.NEGATIVE_INFINITY:stats.winningPlays*100.0/stats.playCount;
    }
    private static double rateNumber(AnalysisMetrics.Stats stats){
        return stats.investment.signum()==0?Double.NEGATIVE_INFINITY:
            stats.recovery.doubleValue()/stats.investment.doubleValue();
    }
    private static double formulaUnit(AnalysisMetrics.Stats stats){
        return stats.formulaSpins==0?Double.NEGATIVE_INFINITY:
            stats.formulaWorkYen.doubleValue()/stats.formulaSpins;
    }

    private void showRows(String title,List<UnifiedLedger.Row> rows){
        LinearLayout panel=new LinearLayout(activity);panel.setOrientation(1);panel.setPadding(12,8,12,8);
        ScrollView scroll=new ScrollView(activity);scroll.addView(panel);
        AnalysisMetrics.Stats stats=AnalysisMetrics.calculate(rows);
        panel.addView(text("遊技 "+stats.playCount+"件・"+stats.playDates.size()+"日 ／ 経費 "+stats.expenseCount+
            "件 ／ 収支 "+FormUi.money(stats.total())+"\n一台ごとの中央値 "+
            (stats.playCount==0?"該当なし（遊技記録なし）":FormUi.money(stats.medianPlay))+
            (stats.playCount>0&&stats.playCount<10?"\n少数件のため傾向判断には使わないでください":""),15));
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle(title).setView(scroll)
            .setNegativeButton("閉じる",null).create();
        List<UnifiedLedger.Row> ordered=new ArrayList<>(rows);
        ordered.sort((a,b)->{int date=b.date.compareTo(a.date);return date!=0?date:b.id.compareTo(a.id);});
        for(int i=0;i<Math.min(200,ordered.size());i++){
            UnifiedLedger.Row row=ordered.get(i);
            panel.addView(button(row.date+" "+row.hall+" ／ "+row.machine+"\n"+
                (row.expense?"経費 ":"遊技 ")+FormUi.money(row.profit),()->{dialog.dismiss();openRow.accept(row);}));
        }
        if(ordered.size()>200)panel.addView(text("直近200件を表示しています。期間を絞ってください。",13));
        if(ordered.size()>0){
            String date=ordered.get(0).date;
            boolean sameDay=true;for(UnifiedLedger.Row row:ordered)if(!date.equals(row.date)){sameDay=false;break;}
            if(sameDay)panel.addView(button("この日のカレンダーを見る",()->{dialog.dismiss();openDay.accept(LocalDate.parse(date));}));
        }
        dialog.show();
    }
    private void showError(Exception error){new AlertDialog.Builder(activity).setMessage(error.getMessage())
        .setPositiveButton("閉じる",null).show();}
}
