from __future__ import annotations

import base64
import zlib
from functools import lru_cache

import quickjs

# The minified token generator is derived from AkShare's MIT-licensed ths.js
# (Copyright 2019-2026 Albert King). It is compressed here to keep the Python
# package small while retaining a deterministic, local token implementation.
_SOURCE_B85 = b"""
c-nn?{de2gdFDC0XPe*lr#<ayHYbre9vKiJS>L2YL5d{Hwrok3CHX_9Xaxd65*7t;0FV;LQclve$##=Wo2`^>o2E%7wzRWt^U)-
2nr4%Kg@=F1KF@nW5|T9?+aPdpaqs*2ywAPBG_0U+>(RrdwcX97ji*Z+yIaevOXkQ#W;8oKF+MdlG&wqzE7d(aa(%C_v1|MOzUyd
?5gCEu8NU9yfe|b-
$`2O|7e6Bf!!~_h)y;rEA%4(UG96wu%*UF~YmZk!ezc$)RrDAu7!}jwjiTv0=rUR`e71VhrKTFk3x>l!0nT)zj3LqO0MktrjAi^x
7K}suWD3R-=81UM;UJFmpT|7t*u*?&+r<yYTSOxs+rwkog0X?0se-WyMbKpn_b}E1esFIe_eLP}s)>>DWW>SHB+B5F6HfAck^)X~
)(OlS@FCqeGBuBbIk>GGE2aj895w{;2w9Gp!99nkXr<n3P!S_Nf;?z^1(9)e2aObDokQ}(ks*9Of-$D>+%r?d2xBtNxEv|UO-jxO
eBRTI=O%qI&e<`5Zan0`7~`%;hleI*Y%$=7vVE)(<$OxVW(&RO*w*ydffLmOug?m~^#jL?!hFP`3qxV8>PDO$S`7tG!wEu1(}!O9
u16)%dcr`uZ{|Jcu+QV9nncP3RiX$!#nE-
6ci$H|5&}HYR5(UvZ+@RL7IJP$yAkQJbZDExV}78i;0<_<==DTPo4*r<oIMi_RUNM!RdRMZtwye!(U4uSf<?dR%txB7BfRS`-
JEOI4J%FaO%{eqfq$?VchW-rq+=7&@PY9`PvFO~z|JLsM<-
%|o$CemOu05FIQmN3jgC@q<q&(uxkhm3vfvO|bJG|AMt$Fk`y2I_rj_jH!rp0fGYVX<d|9u0S1<46Mn@s^m)XRGSwes(lDm1N@o=
F4!AB9PaygF6?sKsjfGK{?F+C$NeKX1_?}!I;QN<01LMK{O0AwK;N3)1RX)pKM_2XmB&5K86y5UZrqEqemIWgD;HcN=m6@424IV!
0=$`q_~l(7N>Ia45<S!p{hmK!6grBZZN$utKY&Z)n~RcLnZ*N4LTUKj-gG=x?d+gZP1hOuvRB~$L5gn377Bw9B(ZfxHM#`fr^{(h
}t)+sn_Cpw@xlhgs`Gc3b3?AYl>Xq1db4$g<%5u|OHo{SI3O*iO^w4ZY^ZZ&O&4Ei)2Zma7O)lVbBEp=U|{%H#l&n(F|s9(XXQjC
ZrT@vF`Wk60`bzeX%L4eq4D_xh~CnwqixbA`Z`UFYd9m-
O}G>ocIF^WdbC>saHvT<lE8S_Td*v&P}s_CP46wLrtqHG>O*Jbn2T!OyyX4Bk_HC{CKj12&LGe0^-
WIq)DESNP(oqe;M7ieD+KOLF7`7vCtnDhBD1nio*nce~lR~U1E;hIFmp~}>5Hs8^lE&wJXdt=C|)f}(5SaGXGZBaKChpb|8!Kqjc
ml-W7h{mdK6}2@zrw|P2*a?6Q0Oo<;aJmCTCnw!W*AtUIntP6`>BYJ3?6`MF(-OkOJstBI?qO17&U}RQ-
m6EbM>=e;=_eed;k(7YWy;o@i_gRWyRCg_l=EXukiaA)AJR}-lwM8O(?^Dwt*d|o1!`5xb~N^E3V2sl`l92wR0MTDFe>zq-kbAgc
TVP6WEPD_`i-Q1QP6z77+YvLat^44ZAEs4H&3Wb&Z&kD^YX@G2T(=3NPy+WryHwlB{h1|P-
qOTh68_fO_p%V^NwKgbYkasgo|$;GVK!&KP0>A=oNOJLsL>MD_^FGFF`0Ye3ZQI32;NZp{@0~9&AsS9UtGA=ShC8@UA#wnkK;j#?
$phbD1E6u42YMO!6wfkai3C1BFAJMcb1Yn8(Zw=lP?(SB@QN+uDKP=%FM{S;Ab`hkWFMrW<=hhk*-
I9*VzlX;*zx0#GpA%0p1V3+Dj9<(HX_<Z2s3cHmf%vs86hEjdFrsl%fA>Pn9_j`%7s!XWXh98fPDAHSkY;!fd0bIU5PSqF|bFPtK
t7rpW|nfm0!u<~|#KVffi609Ni8a7R{OD`C*4Aw`wa^<JRpBOnAe;o0;2+Vb3ArXS;oCv~1XvFczfT7eY=`dX?nCm!wqLpb@<QTy
X5C=9_FmIk{9{_nj5abo~d12f$J~SK*fr{*aaa}FcQezBNUV5M`kestj5Ginxx)}nPO918?pqRkC42WJb3CfO4vrAH6_li!*^&I5
2u_RysH*afA3TH@+BRD|jYYbS!7ALy-F+%1Bnv0@PjSsRJeEO!|L*z}#LzJGpU{wJVcSsaCqL9k~qzw;}BL=fkE&^ea2cm-MN)p5
#+srr8)%0#5znHFE%DT>gjw#P=YZZbTnDacv(LrC$Jf|5HFg3h*ULW%|Rl)aXy_|=6J0q3UNFG;94u4p!%|<TDS21&c%>s8`MrhZ
?jYV;zF*w)&sbEUx^ufWZQJS4KyFH=c6pfbz<><uNl(e7$>w*h~{E}G0OhTeER;=40r-
K$v4yaSD617TD)4CK;u(y1X`uDW!(gBZ*wJ47j{nw<SGc#RD_tG2mCN$F1PCiJd3nzytdyY0ZXw4oFu=QMQ9n+niRZWQVO<+~e?}
)3;eAg0dtCNSpC1UNy#M+Km0(CAhGlg7zrbCc(^^PXtWujcyU)nj_v<K?%V<9<QNMk|ANKJF)_UUT^H^H4_s?*CXMS3m~9<X+1Rs
=dHWDcQG0qOA#X4fI8kIJtg&M&F1$ftw+_%PSFWtyO8rVaYHmk{%kbAj2A0QI2!He)PH2p<OvTG8p)d?Dw}2Dy%X7xHRh0UN+udL
iM<VtSWQgP1%14|+xEngRJn|KnbeU`#T6;+lRrf2dXuE1ESs+kIe3;#3W6;6{~#^m50RjBsfeGTd&vg2uXvz>b&vlgo(GGg(=pJs
_LRD3dj%DvF6HTZAR|%uG|DU@&4x7rF`9o3$xc7H|gjiAUc;ZqaQE0A>)>l2nWROC}j-
K_h17_A%E&eyd}aec<|j&(W*hL{_^tSR{0UtdfgNxE!+k<~){^2QhS4yID~*vAn66u1;HmW80!LH(xBlFVJnoM0vIr#{|MKUqj+1
y!S*~C;AYld_j)mPM45wiLY|Y%8gwu4io+?NdN>qVtsIJm%6yz7oR3QN;Ba&arME7cls0Ix@bfaFUfBG2_<YPFcyb09%5z8tk8R5
vaGf<1Va)G_UN76GFDI2$z_At-0T{<E~QAqr;bvj2YKKoYE~XasqoV8NdgHb3Fi{qzWHU%A4ovGN)#GF2Tg2J$%45Gv6m=#!Q8-
Us7~L-dB!*5IlpH_-9V)R>8gr!BP|$0^0BG~Itj)+rMYgbjhF{Td7EfoFwH%6D*z};-
C)Y(6Z1qydPx$~;|Ujtfo^PSo^G1KoTt_#!zWG<_yM`YE82j2i*gLb9w4nRz-
C@tzm6orGu3QUbMoV|`!=4DMgBH7^(1^azX~FttS5~n{$^N@eVMAt-_Zn;R+6ybt9=+GlM^r22W1y5XU)c2OV;3^?wkJ1jI8UA0S
i{w3JI_&!osh6+f<Pd2v?0EyFJ^`VnVhmCXkw|Ktg-
g&AGq=%hary8QcX?8nn{El}#N0;;b4k*WI1!PFw3)E6Pt~s6O{ZIFTm<!VcU!l~M}O4f2x=w$~`O$H%gn5$`edz&LHE=eY~ZfGu)
MV7zdJr+b`9&lU5KnOirQIa^3~N05~x)I|1^xNo`O>iX>}Ny4O%ApDNJyQ37*QBd-
!DZ4X9s2=s}(IuK))6!`RD>=jJB~mjTF&GFpCm26a;}`SXm7EwCo3mQxCrO;H&P)CSH565Gu_P{mI`;P~=0eR1H?Ux!=y7A1UQGM
x2Ae%T88>72u})v$<gxZN_CDpPa5Gu9e0h{jE1eSJA*Q^;XCb@CX)r70zqA!mOfFfGeBC7=Z4EaJ7qlRs!JtEt6QWQPPBzn931t&
mMbxoX7O@iM$7MfzJS)kC0v0BoGV1ENnBoWkmQ1bAzxD230G^(b&0ivNypQI3WleGhCE63Ns<y`1L3WruKBP;6G7hUVr96NlH10F
gv)nDNB0CVcS_2ie+S{0(U<mj3-_RN$iiFIWKq{3=zzSaoAaN@*jm|b*1>-
d0?QOGjf^ftv=|;YS9LPrs_EhKsaEUon9dmYW>vN5~__UDFQAKO#Ml6v+5q-
Mzq|u$e=P(zUR!+>o+iC_rk(fbtehq5Fol^89SszsU!PAX++Z^aF`r=kk$KHN+E)g$E!GrX2Jh=s9!kwX3H!J{got45-
fmy>TV)W9^rPbMeRr$)Q(X2Us39x4(s`iP<8CKo?ev9VF#ybz;q05DDqBO=g_1Cr)I(@ymn6?=Lh^6U00MCBz@@;wFF|J<Ps24iK
e^2PfbmZ3{Fj{D*2^!pD7ULxMDPzf6150C%z^wCC(P%tQL<}o%I5kedTUfy)7VyeEm)2oXuMPxUPI_^Cdoxid9=XN}6oI<*j>6Ns
OTHi;n)q6j)6DQSyYPIU)+-
FFR#X`ZEU)MvX!<~Mp$1TMVw=vAO>wVKd70ee2&W4`wBGRDE#Y3cMg&nI2}iiyech2$sA8#5^7T1nIWTv6P;#<cDdXgIcn<(jb%7
dg{8H%&$Cfv7gy|(+SGs2|6^Y2`B3Lhm19?tf&$0N`IE1{o18gIb?aN)WO8ltze&|3v=}L3GvskRh8Q3ki{r$GmE@YyFW*93I5dH
O`nqSlOu6{(W7z;p3PT~;Bj9x>#JP|LF-Pk7>ZBi8}VK%I=RLo|{5H`&g5w!cN$%*Cn#9)sx`J`AeBX0qbv_=y}rlJJ6<{ggmZa|
mh5<8#~sxApfVaW3jHDm;?Zzrg=&v2lKBVy?>dCf=;hR71d;{@pyDH+k~k%22idK|=%JmeSxVq&-
IrCq$(XzIO54huMLT^QWMQfp}2bY&pE1)@p`#FN}MVwigO9lCi4D6Y?01k!0ur0oj#PH!c>9;eUcEf_8yWGDL`>i@lWc`f{)Jd_b
CFj0uJ2Q69kGJaI{G8BCbV{%%Ge;YBOh%2U1A#a#UP}?FS%TA|H?hQE&Ftr8OD{8_iI2-
0H>PGUG!yKbHQ}5ggh*ZX7K8=~?>24Nl?P?6G)v0VPVwn`liWKsKIePpOK=dn{HId-
}goiqZ=`_C}s8_2dG$^MJ(k}Rt!|Gq+h71Tpc7z3Ok}N=W*3g0sg60kuC|RH~E&HyP4ioLNkR_M{ed(;s*yS9E1H`5){dYKNd{?R
=gFdEjQ&%Wt+%06c=pB&mykb((ay1Fn-PcFc4Wl_-HKL#%Mow|M0@TnxL<D{KZUhl4mD950@&Q6-
LICgqzeo^jNenoWJL(Gu!9xbzV{~#P(0qZEhz604Q-
wHzB8r$>*m(2|0l&MlytxGla=q91Q9jF!fgWsm^owdxRl=ipk`4T(V)W`W<8gz6W}iYO8@%2$YF-
X9cBzY#XbJLDW2$BRojxpCWB^%Gm}lbX%v9m}U17d;N$O7SnY<pVSmC2XZ$0p9P7pN_UGi2z8#a=?@=ih5I`uK_^xi6SL$v!MUT~
7)pbYYhlB|5PF+6$A0>$aRo8x=aYQ5}wyI%dkRIg=w4IFMQ{U~i;7lHSN_I$tUSl*U@$Fbc5tBSJ6S8fjC%yB+t2`-
StTqG26$FU^ev&iy#TiY~zwZ^Qf%~t^=lHsDMNL7s=v1D18dr&{6K7tv}$_A4}Pq~M-+u)!<>_|oG4N-
J>ihEa5W{ksLcRT%xD;EaKQm-{kmtq=c%=cOYiH6R~mR}Z4jquZ=ZihSRM(6ILsU=00yqX$|zYv;~*Bl9vaZf(XnNnZeaHq-
G=ymX!67c{%tlsJ_KOZE%iMXjBAAi7W?YY!?zrWv)S)*wtMVc(cDt1cwi=m=pbI0132l*v{8#gV~OC=|OQw<l(s2i%9bRzVGZRWi
$Z9HL$WUu?;!&K`KU#+iDc!lU0L=A**PE*9pbF{o|s6USUu~4y-
e{B3ij_6o;VcyUQ8csl7uqJE+c7d3S1@kF>HVWol{OlFt%ID^Hu~>F!poPFc#ItuD3tBkxQ0>aSWv}QQ$(?fN&bnmFTAhlj?30hq
B6$M<vu3VG_vD*fNQ3(2UN60yFS0pGG{mYL6wD7P!Kz;momIb~L|#s|E`k;BOY>o}`B}xOR;76<Zhq)A@A!wFw9UtD^6<JJf{GrY
x%qB$GpF3>4n=+(65Zv-iy_C8=mD|Ohzk*MA-akSp8h(L4EBl8@-
dsb5LQEA=mogdGhgHk)oVp7g3c$NEKRSkwU$gBaO%M6z2mf;>tB^~++`1}8(G&md*>awbJAV=TAaW4fn;yq?zfWpRFpEt#*JI4o4
1UyNh7sW`p<hQV`9QcA;?ljs`}u)hxoZ$wZaO1RjlD;1ph40sy0KMEZ(1AU0PXsw6?oAzp}D0zlcZ1hK*GF?5C|aKWn}H_twSlTj
y_DZ+_W2|9<P@t8)CC*7-&2;%lw*v)0AWS{HxS`sCx*CqHeS|F(7hPw2@>jj%SDGSnAdMk?3m9M#;w2~FHf86yx*-
g~8ZOPcsM@%ajGysY9lJ5Wfc3<y+o8@TNM<1gP(ooPb+Xt(;`zxm!y>PDWO*B+!O`bVv||I~W>1Drp*xq)L?bgFJ?*9k2cDD^1Nm
++Iso0O3qH&P|ER-&@!VB#$7G%}2aaUR;If7(9#7$>6>6FAa}(<$TD%hb>St-s-vmyT-
2_^@#Yfn%hcDRdZuo>K<A5oI4da?x<|g$2qI*u43Q#`ithbH>@{2R^`nq?zKV&2FmVo*OQ&&lijAmW54IFP=|r7oKLVXW`h>$1gJ
5XzFsylyL*LI;=R<fo9rwnnk3a@_#p<)nzB&aK-2GBlE3p-
b)$d@R9f@v`SV$@h^Ra!M@hfea9_VcwTWVOr5&t`{k<Bx9r(NYRsZ27nbL1HGT#`m1}63g0Z9ee=8q;>A%!oq0z1czT6!h8=rtBt
A0SAq*UWp#d+ojRZifkLE2}3)js`g`|O|Fr{8a%ebPStf9<osXrKP1efI74={Y*AS(LR83M#!Q|7OLv_YW;mK5T-
#9;{eixo(x&kfEDzKxai!Xp)!n8>{?r*L_a?a-nM3`wMVbQzZDy*4tmV-hL!0@!Qs$|I<4E^VY>*x6c2zb@7YV`M<U<{tn$R=%|r
_f+<5`){~9pMgO1%$9oY1zE-
O?WAixyC(Uk7r)Bsbwom`OeRk14{aX9%AKRzjlg7VqpZ=_U_BH6(K09rn{tz+QKK(}f>__d>kJ@LyZJ+)Pvj}kq`%V`ZMmcogFsy
C5nt>9)t|I`8iXTR?HNP}De3(-
3@t^+dXW095{m=VS1tXuz;UeBiPsOo~!X6v+&ZAWZ6jX%Wjt;iaq^caJl|UR}2reitC()SeL*2Gqk1*i%jZ9^R`-
X?7DW71Pgo0!5cdx8!)jw2@>3(O4`Nqb^5I}yQe5VhjjoUl;Z#pM2KP*!*<EsY}!c6wMT~}Jfxte<Rc{G0zK1msqBXH6cjOfDC^5
<|UmBeV{NaisD=<u*WLnb3QG3mU|0J*dEn$mp!X3DtTce^YI5u1MmB2|5$J+PdbJM6!+Gi3V*JbE{eyBC#xJU<Eb0>=_KifZBX?c
3o{R0&;lz5Ob@ZCBv9s^fdNS-Xdb=aI!Q=cj%$w(CVsU`fIf1h=POY;V$)b6>I)&Mq<GS6pO)Cz<AK+JRrK3ML&8B{~oy7Y7P55P
+?>KjGhtAGglmw%+_i!u_;${+B8x+NZy2pMAA``mOfakK3o;ZJ)hupMFIG_NVQ$ueVR%0-6={#H;`p_a~=jh}w-
Wmp?~z`=dXkgpn#?HUeP1VtJ8&a18=IftuO*Ah4K2&m3!i)vDp_!SnZLK9@w5FRo0pXpGWl)n3liBh}4r7`=SvdSj#Anl)x1iOkP
FpI=f5%Ho56x5aZCH;Mimsi*6=5IJISyIL=DnBBl)HXRKKa&LqbbaQcId3{UVgu|W{vg6G;PP!X9)e=Tay@!8wj~>K{)M*%$J+z^
LIej|cx3d!!2DJRkot<E3$14ozIGN*<<z6+6Cg+Y$<k4TY-kwSI{ySFbH{WTU|3mBIcdhf^v@Skwoqxphi+_{9zi54OhDXfeEtT^
#=Iq=T^E*3*my8Q~Xo=-
4@*^pPUsJG_DmEEWVO&Z!e7U{GYRf7#iHP?oSg7tZk|^QG7z{hyDfsQPAGA+@(?0uN`}Fs5N$O<2nM}f`6WI(|L+l!sxZT~|P9gZ
0_SxUkcncx|t-D)tt4<M9k0G%~W6DGKPs9~`6nTq;W?qgCkHt?-
jxPyDcQ5Za@nx}dl9?1XaP~a`|I^mRzX&(_Rm#X*PVpFa1E&bqV@JF7fXU>P+zyN?tcEkg0c~zt(tK`OpWE5F{d&|m5jO+VaQz;U
t&rAL{^6Ma;&g#Qonm3}<A}NSZ2RW=_U7%oD^FAF`Q1!@cjJ~|2;2m0kjm@HWynh)h{vG6mHNWV!&@Br6Up7Lv)G)0>-
;<On2k98N{&BopZ*C8E$R&lEswu$pS@|HeUmkbw|+ur;6aw9-?dLsnZDgV`%e1|ol&R1BefaFZ?UQg3@8rT$&oM$w)}-
=<b>*?qFAe1>Z#zkkD7HCIsHV8iH1jki(=hv%Cah`)r=(0&Q386NY&FkVWu#($RZ;F$;hwU6$Ncs1jb$M;gqXNC9v^%_iS4%|C{#
d88|U$2QF(6WYq~n1svBP6Zj5z5G#EhKx}jv(PM>5GT>i}!I|L;%Xgl{tH54)di=QCq|m^UfI0~8_-lT&1#o9MU%zwrcpk{TC-
84uUc;jKnoBB5CAmNpej(@!vwuY}_`AYxykg+H!faMtuYS~*caI7*6!Uw82{VGk7=dBJ`rh?L<5lQ;wOzOD`GG1ApGc{`werU)#M
CC4-
PY?}gLQTw<_wYg9+tU4iC^F13T3@ELjXLwCH&A~{saV<FFafui;=Mw_>ph>RaG}xZI|xMKU&#cdxXWy>iqphLKpq7*gVqf&pL?D$
-Ht1lPr;Jqe0@WefGavZ;{8}<r3!n$4KJV#a951F<OLy!2Xfz4K~Ebv16ttMl%Gkfr0AmAN82;R;6zA4UhCaAi#st3=j9+Tixn07
{Rk#U(JdtW|HnG+y<Q)A(nRG@5XSaJdvNhK0f(!AqIM~kpLE?n}LBhQIjUP_KQA4)9igF37bMv<`)+4EZx0#fBC_~mDROJ>yI}!x
1KzG_I&$=wPzQdQn}*3+OHmXe(i%GjOvZUqvnUhBP8OJne5cyZpTzVZN2>;Qb9fzE;MRjR;PoPimYTtStthR9z%Ta_12qzY`ytr>
->kUiyv`KcJYJO`Bz&Pf7&|#*1PB^{jq-hpKu4I=YJqt!_Wf7IMX3Hp&hujD0Kzhz@CtDQJjx^ez7T#cZtTt7h@PIAa8|Yr>(cY>
L%sYEbdVXYis0TS%vWExI8E8kB{1?KO&-?ej<Z?qxJUZt+#(6RpH-SZ?Fvbeq!ChVCk(uZrVkA*9wcTN?4xPBfnOvH0&2E2X?7Sl
OH;J<ti)J=&W~~N-
j%kRVym_!9mPeCdYdjYy}66<3wJ&>lG|Cc(!WU%b<i+MWtnLsXNN#w$Y)~BeeAhYUaqekXG(03^N<zviB#luKs(;7?izVqw&8Z%S
T|)4d;WpN-RlLzP@7Ue)!pws{IFQ;i1-obesS|plE?AYV)LXbo$g-N-a)kBjF>8VtnzlW$+~-dk8UL@>>01573%=`I_-IaB@@l6Z
IaKFdUznq{BMZz=<N_Pf(6aKsU8xP*~Z0e`n_px3XND?^$lKK9o|+m%H&EjO1iryug5o-
b3zK^=kAU0xLjGX98fUO{jbcDY8>>1dk9)u}W}iO_;?GYGPR~!4U5xFP&p5Hv3qdxSLH3GmdDxBTFVBTe2%48xOa7dEO}*bY3d5o
mYFllu(f9a5qj+JU-
c(^5@*mIQ?Z}vqMpmmG{vJuH+8KoPJAXQa(TTbW^D8R$>o9w)wcFL9)5Eab51P1VQDB(4kf9NS#e(61;q)$=vGIzKL-OPv4Wu3<U
xeAm2ukw%+{j*2O=!&VMJe_=DN(#MI!3a5HfOKY|V=pb+)~$yfGP5#t2P5g~yinI30;zPfTB^h?EL0<pjN*#Ry^K*4wvL4GdF@&7
A42}|(r3YGbW(4#kE+Vl1)kl_u94v+!uG&YW4Mc<TTx8+A1;q)KcXTKL6Xr#!s)YeEf#wJ<klW*^W4=LPI-&t|rj-Og73av^nZN%
+}w?td4%r3sux&YvQq_&*8i+HZzak8euLe^#<x6l5J@<B0fCa?mY40QGiQj)d&-?^&Q4JWMmUg+HKZdafd&&4IVpr8DIF?^vg
"""


@lru_cache(maxsize=1)
def _source() -> str:
    payload = b"".join(_SOURCE_B85.split())
    return zlib.decompress(base64.b85decode(payload)).decode()


def generate_hexin_v() -> str:
    context = quickjs.Context()
    context.eval(_source())
    token = context.eval("v()")
    if not isinstance(token, str) or not token:
        raise RuntimeError("同花顺 hexin-v 生成失败")
    return token
