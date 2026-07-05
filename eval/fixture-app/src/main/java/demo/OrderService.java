package demo;

/**
 * 訂單服務(multi-AP 隔離測試用的 fixture,非真實系統)。
 */
public class OrderService {

    /**
     * 計算運費:滿額免運,未滿依重量計費。
     */
    public int calculateShippingFee(int totalAmount, int weightKg) {
        if (totalAmount >= 1000) {
            return 0; // 滿千免運
        }
        return 60 + weightKg * 10;
    }

    /**
     * 套用會員折扣:VIP 九折,一般會員九五折。
     */
    public int applyMemberDiscount(int amount, boolean vip) {
        return vip ? amount * 90 / 100 : amount * 95 / 100;
    }
}
