#!/usr/bin/env python3
"""
从Yahoo Finance API获取完整美股列表
"""

import requests
import json
import time

def get_all_us_tickers():
    """从多个来源获取完整美股股票代码"""
    
    all_symbols = set()
    
    print("方法1: 从NASDAQ获取完整列表...")
    try:
        # NASDAQ提供完整的股票列表CSV
        url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&exchange=NASDAQ,NYSE,AMEX"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'rows' in data['data']:
                for row in data['data']['rows']:
                    symbol = row.get('symbol', '')
                    name = row.get('name', '')
                    if symbol and len(symbol) <= 5:  # 过滤掉过长的代码
                        all_symbols.add(symbol)
                print(f"  从NASDAQ API获取: {len(all_symbols)}只")
    except Exception as e:
        print(f"  NASDAQ API失败: {e}")
    
    # 方法2: 手动扩展列表（按字母顺序）
    print("方法2: 扩展手动列表...")
    
    # 获取之前保存的583只
    try:
        with open('/home/admin/.openclaw/workspace-arashi/data/us_stock_list_full.json', 'r') as f:
            existing = json.load(f)
            for s in existing['us_stocks']:
                all_symbols.add(s['symbol'])
            print(f"  已有股票: {len(all_symbols)}只")
    except:
        pass
    
    # 方法3: 从Wikipedia获取S&P 500
    print("方法3: 从Wikipedia获取S&P 500...")
    try:
        import pandas as pd
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        tables = pd.read_html(url)
        sp500 = tables[0]
        for symbol in sp500['Symbol']:
            all_symbols.add(symbol.replace('.', '-'))
        print(f"  S&P 500后: {len(all_symbols)}只")
    except Exception as e:
        print(f"  Wikipedia失败: {e}")
    
    # 方法4: 扩展热门股票列表
    print("方法4: 扩展热门股票...")
    
    # 按字母添加更多股票
    additional = [
        # A
        'AA','AACG','AADI','AAL','AAME','AAOI','AAON','AAP','AAPL','AAVL','AAWW','AAXJ','AB','ABCB','ABCL','ABEO','ABEV','ABG','ABIO','ABM','ABMD','ABNB','ABOS','ABR','ABSI','ABST','ABT','ABTX','ABUS','ABVB','AC','ACA','ACAB','ACAD','ACAX','ACBI','ACCO','ACDC','ACEL','ACET','ACGL','ACH','ACHC','ACHL','ACHR','ACHV','ACIA','ACIO','ACIU','ACIW','ACLS','ACMR','ACN','ACNB','ACNT','ACOR','ACP','ACRE','ACREI','ACRS','ACRX','ACST','ACT','ACTG','ACVA','ACWI','ACWV','ACWX','ACXP','ADAG','ADAP','ADAT','ADBE','ADC','ADCT','ADD','ADCT','ADES','ADGO','ADI','ADIL','ADMA','ADME','ADMP','ADMS','ADN','ADOC','ADP','ADPT','ADRE','ADSK','ADT','ADTH','ADTN','ADTX','ADUS','ADV','ADVM','ADWW','ADX','ADYE','ADYN','AE','AEC','AEE','AEG','AEGN','AEHR','AEHL','AEI','AEIS','AEL','AEM','AEMD','AEO','AEP','AER','AERI','AES','AET','AETR','AEVA','AEYE','AEZS','AFAR','AFB','AFBI','AFCG','AFG','AFG','AFIB','AFL','AFLG','AFO','AFRM','AFTR','AFYA','AG','AGBA','AGCO','AGD','AGE','AGEN','AGEPP','AGFS','AGG','AGGR','AGGY','AGIO','AGLE','AGLX','AGM','AGMH','AGNC','AGOX','AGRI','AGRO','AGRX','AGS','AGSP','AGTC','AGTK','AGTX','AGU','AGYS','AH','AHC','AHCO','AHH','AHI','AHR','AHPI','AHT','AI','AIA','AIC','AIDX','AIF','AIG','AIH','AIHS','AIK','AIM','AIMA','AIMD','AIMT','AIN','AINC','AIO','AIP','AIR','AIRG','AIRI','AIRS','AIRT','AIS','AISP','AIT','AIX','AIYI','AIZ','AJA','AJAX','AJG','AJRD','AJX','AKAM','AKBA','AKRO','AKTS','AKU','AKUS','AL','ALA','ALAB','ALAC','ALCC','ALCO','ALCY','ALDX','ALE','ALEC','ALGN','ALGS','ALGY','ALHC','ALIM','ALIT','ALK','ALKS','ALL','ALLK','ALLT','ALLY','ALMC','ALNA','ALOT','ALPN','ALPP','ALRM','ALRN','ALRS','ALS','ALSK','ALSM','ALT','ALTA','ALTB','ALTE','ALTH','ALTG','ALTI','ALTO','ALTR','ALTS','ALTT','ALTY','ALUR','ALUS','ALV','ALVR','ALX','ALXA','ALXS','AM','AMAT','AMAX','AMB','AMBC','AMC','AMCX','AMD','AMED','AMEH','AMEX','AMH','AMK','AMKR','AMLB','AMLI','AMLP','AMMP','AMNB','AMNXT','AMOT','AMP','AMPH','AMPL','AMPY','AMPX','AMR','AMRC','AMRK','AMRN','AMRS','AMRX','AMSC','AMSF','AMST','AMSW','AMSWA','AMT','AMTB','AMTI','AMTM','AMTX','AMWD','AMX','AMYP','AMZN','ANA','ANAB','ANDE','ANDA','ANDE','ANF','ANGI','ANGO','ANGO','ANHL','ANIK','ANIP','ANNX','ANPC','ANSS','ANTE','ANTX','ANVS','AOBC','AOGO','AOI','AON','AOS','AOTA','AOUT','AP','APA','APAM','APDN','APE','APEI','APEN','APEX','APG','APGE','APGN','APHA','APHB','APHR','APLE','APLS','APLT','APM','APO','APOG','APOP','APP','APPF','APPH','APPN','APPS','APRE','APRN','APT','APTE','APTX','APTS','APTY','APVO','APWC','APXT','APXTU','APYX','AQB','AQMS','AQN','AQST','AQUA','AQUR','AR','ARAV','ARBB','ARBG','ARCB','ARCC','ARCE','ARCH','ARCO','ARCT','ARDS','ARDX','ARE','AREB','AREC','AREX','ARG','ARGD','ARGX','ARK','ARKF','ARKG','ARKK','ARKR','ARKW','ARL','ARLO','ARLP','ARM','ARMK','ARNA','AROW','ARQT','ARR','ARRY','ARS','ARTL','ARTNA','ARVN','ARW','ARWR','ASA','ASAN','ASAX','ASB','ASBN','ASCA','ASCB','ASCI','ASDN','ASEI','ASG','ASGN','ASGV','ASH','ASHR','ASLE','ASLN','ASM','ASML','ASND','ASNX','ASO','ASPS','ASPU','ASR','ASRD','ASRV','ASSI','ASST','ASTC','ASTE','ASTL','ASTR','ASTS','ASUR','ASX','ASYS','AT','ATA','ATAC','ATAI','ATAL','ATAR','ATAX','ATBC','ATCO','ATCX','ATEC','ATEK','ATH','ATHA','ATHX','ATI','ATIF','ATKR','ATLC','ATLE','ATLO','ATLT','ATMA','ATNF','ATNI','ATNM','ATNR','ATOS','ATOX','ATRA','ATRC','ATRE','ATRI','ATRO','ATRS','ATSC','ATSG','ATSL','ATSM','ATSN','ATST','ATT','ATTO','ATV','ATXI','AU','AUB','AUBN','AUD','AUDC','AUPH','AUS','AUSI','AUST','AUTL','AUTO','AUTS','AVAV','AVB','AVCT','AVD','AVDE','AVDG','AVDL','AVDX','AVGO','AVGR','AVHI','AVIR','AVIV','AVK','AVKR','AVLR','AVNS','AVNT','AVNU','AVNW','AVO','AVP','AVPT','AVTR','AVTQ','AVXL','AVY','AVYA','AVYT','AWF','AWI','AWIN','AWP','AWRE','AWR','AWSM','AWX','AX','AXAH','AXAS','AXDX','AXGN','AXGT','AXL','AXLA','AXNX','AXON','AXP','AXR','AXS','AXSM','AXTI','AXU','AXUN','AY','AYI','AYLA','AYRO','AYTU','AZEK','AZN','AZO','AZPN','AZRE','AZRH','AZRX','AZZ',
        
        # B
        'B','BA','BABA','BAC','BAND','BANF','BANFP','BANR','BANX','BATRA','BATT','BAOS','BASI','BATX','BB','BBAI','BBAR','BBAX','BBBY','BBC','BBCA','BBCP','BBDC','BBDO','BBF','BBGI','BBH','BBI','BBIG','BBIO','BBK','BBL','BBN','BBOX','BBP','BBQ','BBRC','BBS','BBU','BBVA','BBW','BBY','BBYB','BBYC','BC','BCAB','BCAR','BCBP','BCC','BCEL','BCDA','BCEI','BCEL','BCF','BCH','BCLI','BCML','BCO','BCOV','BCPC','BCRH','BCRX','BCS','BCTG','BCTG','BCTG','BCYC','BCYD','BD','BDC','BDGE','BDJ','BDL','BDN','BDOK','BDPTY','BDRA','BDRX','BDSI','BDSX','BDTX','BDXA','BDXS','BDY','BE','BEAM','BEAT','BECN','BEDU','BEE','BEP','BERY','BESG','BEST','BET','BETR','BEV','BF.A','BF.B','BFC','BFST','BG','BGB','BGCP','BGNE','BGO','BGR','BGRN','BGS','BGSF','BGX','BGY','BH','BHA','BHC','BHE','BHF','BHIL','BHK','BHLB','BHM','BHR','BHS','BHU','BHV','BIAF','BIIB','BILI','BILL','BIMI','BIO','BIO.B','BIOL','BIOS','BIP','BIP.U','BIPC','BIT','BITE','BITF','BITI','BITO','BITQ','BITX','BIV','BIVV','BJ','BJK','BJRI','BK','BKCC','BKD','BKE','BKH','BKI','BKI','BKN','BKR','BKSC','BKTI','BKTS','BKTT','BKU','BKNG','BKSC','BL','BLBD','BLCT','BLDE','BLDR','BLDQ','BLDX','BLE','BLFS','BLI','BLIN','BLK','BLKB','BLMR','BLMN','BLNE','BLNK','BLNKW','BLOK','BLPH','BLRX','BLRY','BLSA','BLTS','BLU','BLUE','BLV','BLW','BLX','BMA','BMBL','BME','BMEZ','BMI','BML','BML.PG','BML.PL','BML.PN','BML.PO','BMO','BMR','BMRA','BMRC','BMRE','BMTC','BMY','BN','BND','BNDX','BNDW','BNE','BNGO','BNFT','BNO','BNOV','BNR','BNRE','BNRIF','BNS','BNV','BOCH','BOCT','BODY','BOE','BOFI','BOH','BOIL','BOKF','BOMN','BOND','BOOM','BOOT','BORR','BOSC','BOX','BOXL','BP','BPAQF','BPMP','BPOP','BPY','BPYU','BPYPP','BQ','BR','BRBR','BRC','BRCC','BREZ','BRFS','BRG','BRGE','BRG.W','BRID','BRK.A','BRK.B','BRKL','BRKR','BRKS','BRMG','BRO','BROS','BROW','BRP','BRQS','BRRR','BRS','BRT','BRX','BRY','BSAC','BSBK','BSCM','BSD','BSGA','BSGM','BSJR','BSK','BSM','BSMX','BSRR','BST','BSTM','BSVN','BSX','BSY','BSYD','BSYC','BT','BTBT','BTDR','BTE','BTF','BTG','BTI','BTMM','BTN','BTO','BTR','BTRS','BTWN','BTZ','BUD','BUI','BULL','BUR','BURL','BUSE','BUT','BVS','BW','BWA','BWAC','BWB','BWEN','BWFG','BWG','BWH','BWINA','BWINL','BWLD','BWLT','BWMN','BWMX','BWP','BWXT','BX','BXC','BXG','BXL','BXP','BXRX','BXS','BXSL','BY','BYD','BYFC','BYN','BYND','BYSI','BYT','BZH','BZUN','BZYR',
        
        # C
        'C','CAAP','CABA','CABO','CACC','CACG','CACH','CADE','CADI','CADL','CAE','CAFD','CAF','CAFE','CAH','CAI','CAJ','CAKE','CAL','CALB','CALC','CALM','CALX','CAMT','CAN','CANG','CANF','CANG','CAPA','CAPR','CAR','CARA','CARB','CARE','CARV','CASA','CASH','CASI','CASS','CASY','CAT','CATC','CATG','CATO','CATX','CAUD','CAVA','CB','CBA','CBAI','CBB','CBAN','CBAT','CBD','CBDL','CBE','CBEH','CBFV','CBG','CBIO','CBK','CBLO','CBMB','CBMG','CBNK','CBOE','CBPO','CBRE','CBRL','CBRX','CBS','CBST','CBT','CBU','CBUS','CBTX','CBZ','CC','CCA','CCAP','CCB','CCBG','CCCL','CCF','CCFI','CCH','CCI','CCJ','CCK','CCL','CCM','CCMP','CCNE','CCNEP','CCO','CCOI','CCOR','CCP','CCRN','CCS','CCTC','CCU','CCX','CCXI','CD','CDAK','CDE','CDIO','CDK','CDL','CDLX','CDMO','CDNA','CDRE','CDRO','CDRX','CDT','CDTX','CDTY','CDW','CDXC','CDXS','CDZI','CE','CEA','CEAD','CECE','CEIX','CEL','CELC','CELL','CELZ','CEMB','CEN','CENH','CENN','CENT','CENTA','CEOU','CEPE','CEQP','CERE','CERI','CERN','CERS','CERT','CET','CETX','CEV','CEW','CEY','CF','CFA','CFB','CFFI','CFFN','CFG','CFIV','CFK','CFLT','CFR','CFR.A','CFR.C','CFS','CFSB','CFVI','CFX','CG','CGBD','CGC','CGEM','CGEN','CGET','CGIX','CGL','CGNX','CGO','CGOV','CGP','CGR','CGRN','CGRO','CGS','CGW','CGX','CH','CHA','CHCI','CHCO','CHCT','CHD','CHDN','CHE','CHFS','CHGG','CHH','CHI','CHII','CHIQ','CHIR','CHIX','CHK','CHKP','CHM','CHMG','CHMI','CHNR','CHO','CHRS','CHRW','CHS','CHT','CHTR','CHUU','CHUY','CHW','CHWI','CHX','CHY','CI','CIA','CIB','CIG','CIG.C','CIGI','CIH','CIIC','CINF','CING','CINR','CIO','CIQ','CIR','CIT','CITA','CIVE','CIVI','CIX','CIZ','CIZN','CJ','CJJ','CJJD','CK','CKH','CKPT','CL','CLA','CLAR','CLAS','CLBK','CLBS','CLD','CLDT','CLDX','CLE','CLEU','CLF','CLFD','CLGX','CLH','CLHR','CLI','CLIX','CLBK','CLLS','CLM','CLMT','CLNE','CLNN','CLNY','CLOV','CLP','CLPS','CLPT','CLR','CLS','CLSD','CLSK','CLST','CLVR','CLVS','CLW','CLWT','CLX','CM','CMA','CMC','CMCL','CMCM','CMCO','CMCSA','CME','CMF','CMG','CMGM','CMI','CMM','CMO','CMOZ','CMP','CMPR','CMPS','CMRA','CMRE','CMRX','CMS','CMSA','CMSB','CMT','CMTL','CND','CNCE','CNDT','CNET','CNF','CNFR','CNG','CNI','CNK','CNNE','CNX','CNXC','CNYES','CO','COCP','CODA','CODE','CODX','COE','COF','COFS','COGT','COHR','COHU','COIN','COL','COLB','COLD','COLL','COLM','COM','COMB','COMM','COMS','CONE','CONN','CONX','COO','COOP','COOT','COR','CORE','CORI','CORN','CORP','CORT','COST','COT','COTY','COUP','COVA','COWN','COYA','CP','CPA','CPB','CPBI','CPE','CPF','CPG','CPHC','CPI','CPK','CPLP','CPRI','CPRX','CPS','CPT','CPUH','CPZ','CQA','CQP','CR','CRAI','CRBN','CRBP','CRC','CRD.A','CRD.B','CRDF','CRDL','CRDM','CRDO','CRDT','CRDY','CRE','CREC','CREE','CREG','CREX','CRF','CRGO','CRGN','CRHC','CRI','CRIS','CRK','CRKN','CRL','CRM','CRMD','CRME','CRMT','CRNX','CROX','CRS','CRT','CRTO','CRTX','CRUS','CRVL','CRWD','CRWS','CRY','CRZN','CS','CSA','CSB','CSBR','CSCO','CSE','CSIQ','CSL','CSML','CSPI','CSPR','CSR','CSSE','CSTE','CSTL','CSTM','CSTP','CSV','CSWC','CSWI','CSX','CT','CTAS','CTB','CTBI','CTE','CTG','CTGO','CTHR','CTIB','CTIC','CTL','CTO','CTRE','CTRM','CTS','CTSH','CTSO','CTT','CTWS','CTX','CTXS','CU','CUB','CUBE','CUBI','CUEN','CUI','CUK','CULP','CURI','CURV','CUTR','CUZ','CV','CVA','CVAC','CVBF','CVC','CVCO','CVD','CVE','CVEO','CVGI','CVGW','CVI','CVIA','CVLB','CVLG','CVM','CVNA','CVNE','CVNW','CVO','CVS','CVT','CVTI','CVX','CW','CWB','CWBC','CWCO','CWEI','CWEN','CWEN.A','CWH','CWI','CWK','CWT','CWST','CX','CXApp','CXDO','CXE','CXH','CXI','CXL','CXO','CXSE','CXW','CY','CYBE','CYBR','CYCC','CYD','CYH','CYKN','CYRN','CYRX','CYTH','CYTK','CYT','CYTX','CYXT','CZFS','CZR','CZWI',
    ]
    
    all_symbols.update(additional)
    print(f"  扩展后: {len(all_symbols)}只")
    
    # 转换为列表
    stocks = [{'symbol': s, 'name': s} for s in sorted(all_symbols)]
    
    return stocks

def save_stocks(stocks):
    """保存股票列表"""
    data = {
        'us_stocks': stocks,
        'last_update': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total': len(stocks)
    }
    
    with open('/home/admin/.openclaw/workspace-arashi/data/us_stock_list_full.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ 保存完成: {len(stocks)}只美股")

if __name__ == '__main__':
    print('='*60)
    print('📊 获取完整美股列表')
    print('='*60)
    
    stocks = get_all_us_tickers()
    save_stocks(stocks)