package jp.local.pachiboledger;

import java.math.BigDecimal;

public final class PachinkoWorkTest {
    private static BigDecimal n(String value){return new BigDecimal(value);}
    private static void equal(long expected,long actual){if(expected!=actual)throw new AssertionError(expected+" != "+actual);}
    private static void near(String expected,BigDecimal actual){
        if(actual.subtract(n(expected)).abs().compareTo(n("0.000001"))>0)
            throw new AssertionError(expected+" != "+actual);
    }
    private static void invalid(Runnable call){
        try{call.run();throw new AssertionError("invalid input accepted");}
        catch(IllegalArgumentException expected){}
    }
    public static void main(String[] args){
        BigDecimal equal=PachinkoWork.unit(n("20"),n("25"),n("100"),4,1);
        near("10",equal);equal(10000,PachinkoWork.workYen(equal,1000));
        BigDecimal cash=PachinkoWork.unit(n("20"),n("20"),n("0"),100,28);
        near("-5.35714285714285",cash);equal(-5357,PachinkoWork.workYen(cash,1000));
        near("0",PachinkoWork.unit(n("20"),n("20"),n("100"),100,28));
        near("25",PachinkoWork.unit(n("20"),n("40"),n("100"),4,1));
        invalid(()->PachinkoWork.unit(n("0"),n("20"),n("50"),100,28));
        invalid(()->PachinkoWork.unit(n("20"),n("20"),n("101"),100,28));
        invalid(()->PachinkoWork.unit(n("20"),n("20"),n("50"),0,28));
        invalid(()->PachinkoWork.unit(n("20"),n("20"),n("50"),5,1));
        invalid(()->PachinkoWork.workYen(equal,0));
        near("20.5",PachinkoWork.parse("２０．５","回転率"));
        System.out.println("PACHINKO_WORK_PASS");
    }
}
