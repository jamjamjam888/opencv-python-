#!/usr/bin/env python
#coding:utf-8

#(備考)
#参照:https://helloidea.org/index.php/archives/1925.html
#cv2.getBuildInformation()でViedoI/Oが有効化されているか確認。「FFMPEG」が有効ならok!
import paho.mqtt.subscribe as subscribe
import paho.mqtt.publish as publish

import time
from time import sleep
import math
import cv2
import numpy as np
from datetime import datetime
#import pandas as pd

#opencvの情報をプリント
#print(cv2.getBuildInformation())

####################################
#params

#fps設定
#fps = 1にすると背景差分がうまくいかなくなるので注意。
#また、fps = 2にしてキーボード入力の待機時間を0.5sにして無理やりfps=1と同等の動きにすることもできないので注意。
fps = 2

#カメラ視野設定
height = 480
width = 640

#重心座標を中心とした視野設定
threshold_pxl = 200
#dynamic range:200*8/3=120mm/s

#diff_threshold
#背景差分をとるのしきい値。0~255で数値が低いほど簡単に差分を検出する。逆に数値が高いほど変化に強い。
diff_threshold = 60

#検出する点数のしきい値。しきい値=同時に検出できる物体数に最大値と考えてよい
threshold_points = 10


#積分時間(integration_time)設定
frame_integration = 3
fps_t = fps*frame_integration

#差分ではじくノイズのしきい値。差分で検出した面積が一定値以下のものをはじくようにする。検出する物体サイズにもとづいてパラメータチューニングを行う・
area_size = 1000

#detect_id
id = 0

#frame_num
frame_num = 0

#post_vector_infoリスト
post_vector_info = []

###################
#膨張処理・収縮処理回数
noize_iters = 3

#処理が重くなるので必要かどうか要検討
###################


#captureクラスの呼び出し
cap = cv2.VideoCapture(0)

#backgroundを任意のタイミングで撮影する
while True:
    ret, frame = cap.read()
    #ret:errorのbool
    
    gray_background = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    #グレースケール化した背景を保存
    cv2.imshow("background_capture", gray_background)

    k = cv2.waitKey(1)&0xff # キー入力を待つ
    if k == ord('p'):
        # 「p」キーで画像を保存
        date = datetime.now().strftime("%Y%m%d_%H%M%S")
        #path = "/home/pi/" + "background" + date + ".png"
        path = "/home/pi/Desktop/background.png"
        cv2.imwrite(path, frame) # ファイル保存

        cv2.imshow(path, frame) # キャプチャした画像を表示
        break

# キャプチャをリリースして、ウィンドウをすべて閉じる
cap.release()
cv2.destroyAllWindows()
print("背景撮影完了")
###########################################################################################

#背景差分用のbackgroundを読み込む
background = cv2.imread("/home/pi/Desktop/background.png",1)
#gray_background = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)

#移動量を書き込むテキストファイルを生成し日付を書き込む
f = open("/home/pi/Desktop/vector_info_log.txt","w")
f.write(str(date)+'\n')
f.close()

f = open("/home/pi/Desktop/frame_info_log.txt","w")
f.write(str(date)+'\n')
f.close()
#背景差分による流速計測
#captureクラスの呼び出し
cap = cv2.VideoCapture(0)

#fps設定
#上記のparamsのところで指定する
cap.set(cv2.CAP_PROP_FPS, fps)
#うまくいけばtrueを返す
#setメソッドがtrueを返しても指定した値に変更されるとは限られないので注意。カメラに対応していないFPSを指定するとsetメソッドはtrueを返すが、値はそのとおりには変更されない

print(int(cap.get(cv2.CAP_PROP_FPS)))

#カメラ視野設定
#480*640だと動く。画素数が1000*1000

cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)


#高速化？するためにnumpy配列を使用
ball_pre = np.array([])
np_ball_pos = np.array([])

#背景差分で検出した輪郭を格納するリスト
areas = []
#検出した物体の重心を格納するためのリスト
ball_pos = []
#検出した物体の直前のフレームにおける重心座標
pre_ball_pos = []

#算出したvector
vector_diff = []

#多分使うidの紐付けリスト
vector = []


#直前のフレームの中心座標を格納するためのリスト
pre_vector_info = None
#計算して求めた流速の値。
velocity = None

#移動量の絶対値の和を評価する。
abs_function = 0
#更新変数
new_abs_function = 0

#loopの最後にclearするコードを書く

while (True):
    #VideoCaptureから1フレーム読み込む
    ret, frame = cap.read()
    
    #frame_num更新
    frame_num += 1
    
    #timestamp
    #現在の日時を取得
    #now.secondで秒、now.microsecondでミリ秒を取得する
    now = datetime.now()
    timestamp = str(now.minute) + "分" + str(now.second) + "秒" + str(now.microsecond) + "ミリ秒"

    #出力1:差分でどのように物体が検出されるか確認する
    gray1 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    #差分検出
    color_diff_ini = cv2.absdiff(gray1, gray_background)
    #閾値処理
    retval, black_diff = cv2.threshold(color_diff_ini, diff_threshold, 255, cv2.THRESH_BINARY)
    
    #ノイズ除去
    #operator
    operator = np.ones((3, 3), np.uint8)
    #膨張処理
    black_diff = cv2.dilate(black_diff, operator, iterations = noize_iters)
    #収縮処理
    black_diff = cv2.erode(black_diff, operator, iterations = noize_iters)
    
    #加工ありの画像を表示    
    cv2.imshow('black_diff',black_diff)

    #################################################################

    #出力2:こっちで重心や矩形を書き込む
    
    #重心を計算していpく
    
    #①差分により検出した物体のうち、その領域面積が小さいものは光の反射のよるノイズとしてはじく
    contours, hierarchy = cv2.findContours(black_diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:#cnt:輪郭#輪郭の数だけループする
        area = cv2.contourArea(cnt)#cv2.contourArea(cnt):領域が占める面積を計算
        if area > area_size:#輪郭の面積がthreshold以上の場合、リストに追加する
            epsilon = 0.1*cv2.arcLength(cnt,True)
            #領域を囲む周囲長を計算する
            #第二引数は対象とする領域が閉じている(True)か単なる曲線かを表すフラグ
            
            approx = cv2.approxPolyDP(cnt,epsilon,True)
            #approx:輪郭の近似を行う
            #第二引数は実際の輪郭と近似輪郭の最大距離を表し近似の精度を表すパラメータ
            
            areas.append(approx)
            #近似した座標を格納

    #重心を描画
    #②検出した物体の数だけ重心位置を計算、配列に格納する
    #重心を計算する方法はいくつかある。
    #今回は、輪郭から計算して求めた。
    #各検出物体の輪郭を構成するすべての点をnとすると、重心x座標はすべてのx座標を足し合わせ、最後にnで割れば平均となるので計算できる。
    
    detect_numbers = len(areas) #検出した物体の数
    
    
    
    #####################################################
    if detect_numbers > threshold_points: #検出した物体の数が異常に多い場合、カメラが動いた等の問題が発生していると考える
        print("too much detect!")
        break
    #####################################################
    
    
    
    for detect_id in range(detect_numbers): #各検出物体の重心を計算
        
        n = len(areas[detect_id]) #各検出物体の輪郭を構成する座標数
        x, y = 0.0, 0.0 #x,yの初期値。local変数
        for coords in range(n): #すべての輪郭を構成する点の座標の和を計算する。※coords=coordinates:座標
            x += areas[detect_id][coords][0][0]
            y += areas[detect_id][coords][0][1]

        #重心計算
        x_moment = int(x/n)
        y_moment = int(y/n)

        ball_pos.append([x_moment, y_moment])
    
    #ball_pos出力
    print("moment:\n"+ str(ball_pos))


    #id,x_moment,y_moment,frame_numの値を持ったリストを生成し、テキストファイルに書き込んでいく
    #そういや符号器検出で、一番左側に存在する点を、四角形の輪郭の左上の座標としていたので、左側から縦に走査していってるのかもしれない
    
    #検出した物体が存在しない場合
    if len(ball_pos) == 0:
        
        #post_vector_infoにframe番号のみを渡す
        post_vector_info.append([None, None, frame_num, timestamp])
        #テキストファイルに書き込む
        #移動量を書き込むテキストファイルを生成し日付を書き込む
        f = open("/home/pi/Desktop/vector_info_log.txt","a")
        f.write(str(post_vector_info)+'\n')
        f.close()
        
    #検出した物体が存在する場合
    else:
        
        #検出した物体にそれぞれidを与え、その座標とその時のframe_numを渡してテキストファイルに書き込む
        #一旦格納してあとから再度読み出す
        for iter in range(len(ball_pos)):
            #格納されている重心座標を順番に取り出し、id,x,y,frameを渡す
            post_vector_info.append([id, ball_pos[iter], frame_num, timestamp])
          
            #移動量を書き込むテキストファイルを生成し日付を書き込む
            f = open("/home/pi/Desktop/vector_info_log.txt","a")
            f.write(str(post_vector_info[iter])+'\n')
            f.close()
            
            #id更新
            id += 1
        
            #重心座標を書き込む
            cv2.circle(frame, tuple(ball_pos[iter]), 1, (0, 0, 255), thickness = 10)

    cv2.imshow('Moment Frame', frame)
    
    #リストの中身を消去
    print("clear")
    areas.clear()
    ball_pos.clear()
    vector.clear()
    
    #毎回リストの中身をクリアする
    post_vector_info.clear()
        
    #キー入力を1ms待って、k がpだったらBreakする
    k = cv2.waitKey(500)&0xff # キー入力を待つ

    if k == ord('p'):
        break

# キャプチャをリリースして、ウィンドウをすべて閉じる
cap.release()
cv2.destroyAllWindows()
print("終了")






