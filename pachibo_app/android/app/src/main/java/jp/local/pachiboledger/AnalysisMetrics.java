package jp.local.pachiboledger;

import java.math.BigInteger;
import java.util.*;

/** Descriptive measures only: a winning history is not a prediction. */
final class AnalysisMetrics {
    private AnalysisMetrics() {}

    static final class Stats {
        int playCount,expenseCount,knownTimeCount,winningPlays,winningDays,flowCount,spinCount,workCount,formulaCount,manualWorkCount;
        long knownMinutes,spins,workSpins,formulaSpins;
        BigInteger playProfit=BigInteger.ZERO,expenseProfit=BigInteger.ZERO;
        BigInteger investment=BigInteger.ZERO,recovery=BigInteger.ZERO,workYen=BigInteger.ZERO,matchedWorkYen=BigInteger.ZERO,formulaWorkYen=BigInteger.ZERO;
        BigInteger medianPlay=BigInteger.ZERO,medianDay=BigInteger.ZERO,maxDrawdown=BigInteger.ZERO;
        final SortedMap<String,BigInteger> days=new TreeMap<>();
        final Set<String> playDates=new HashSet<>();
        final int[] distribution=new int[5];
        BigInteger total(){return playProfit.add(expenseProfit);}
        BigInteger hourly(){return knownMinutes==0?null:knownTimeProfit.multiply(BigInteger.valueOf(60))
            .divide(BigInteger.valueOf(knownMinutes));}
        private BigInteger knownTimeProfit=BigInteger.ZERO;
    }

    static Stats calculate(Collection<UnifiedLedger.Row> rows) {
        Stats result=new Stats();
        List<BigInteger> plays=new ArrayList<>();
        for(UnifiedLedger.Row row:rows) {
            if(row.profit==null)continue;
            result.days.merge(row.date,row.profit,BigInteger::add);
            if(row.expense){result.expenseCount++;result.expenseProfit=result.expenseProfit.add(row.profit);continue;}
            result.playCount++;result.playProfit=result.playProfit.add(row.profit);plays.add(row.profit);
            if(row.investment!=null&&row.recovery!=null){
                result.flowCount++;result.investment=result.investment.add(row.investment);
                result.recovery=result.recovery.add(row.recovery);
            }
            if(row.spins!=null){result.spinCount++;result.spins=Math.addExact(result.spins,row.spins);}
            if(row.workYen!=null){
                result.workCount++;result.workYen=result.workYen.add(BigInteger.valueOf(row.workYen));
                if("pachinko_formula".equals(row.workSource)){
                    result.formulaCount++;result.formulaWorkYen=result.formulaWorkYen.add(BigInteger.valueOf(row.workYen));
                    if(row.spins!=null)result.formulaSpins=Math.addExact(result.formulaSpins,row.spins);
                }else result.manualWorkCount++;
                if(row.spins!=null&&row.spins>0){
                    result.workSpins=Math.addExact(result.workSpins,row.spins);
                    result.matchedWorkYen=result.matchedWorkYen.add(BigInteger.valueOf(row.workYen));
                }
            }
            result.playDates.add(row.date);
            if(row.profit.signum()>0)result.winningPlays++;
            int bucket=row.profit.compareTo(BigInteger.valueOf(-20000))<0?0:
                row.profit.signum()<0?1:row.profit.signum()==0?2:
                row.profit.compareTo(BigInteger.valueOf(20000))>0?4:3;
            result.distribution[bucket]++;
            if(row.durationMinutes!=null&&row.durationMinutes>0){
                result.knownTimeCount++;result.knownMinutes+=row.durationMinutes;
                result.knownTimeProfit=result.knownTimeProfit.add(row.profit);
            }
        }
        result.medianPlay=median(plays);
        result.medianDay=median(new ArrayList<>(result.days.values()));
        BigInteger running=BigInteger.ZERO,peak=BigInteger.ZERO;
        for(BigInteger amount:result.days.values()){
            if(amount.signum()>0)result.winningDays++;
            running=running.add(amount);if(running.compareTo(peak)>0)peak=running;
            BigInteger fall=peak.subtract(running);
            if(fall.compareTo(result.maxDrawdown)>0)result.maxDrawdown=fall;
        }
        return result;
    }

    private static BigInteger median(List<BigInteger> values) {
        if(values.isEmpty())return BigInteger.ZERO;
        values.sort(Comparator.naturalOrder());int middle=values.size()/2;
        if(values.size()%2==1)return values.get(middle);
        BigInteger sum=values.get(middle-1).add(values.get(middle));
        BigInteger rounded=sum.abs().add(BigInteger.ONE).divide(BigInteger.valueOf(2));
        return sum.signum()<0?rounded.negate():rounded;
    }
}
