# -*- coding: utf-8 -*-

"""
@author: 
@time:
@description: 
"""

import re
import os
import json
import logging
import traceback

import pikepdf
import pdfplumber
from PIL import Image


def decrypt_pdf(old_path, new_path):
    """
    pdf解密
    """
    with pikepdf.open(old_path) as pdf:
        pdf.save(new_path)


def find_questions(texts):
    text_list = texts.split('\n')
    questions = []
    for text in text_list:
        if not text.strip():
            continue
        if '.......' in text:
            text_all = text.split('...')
            q = text_all[0].strip()
            page_num_start = text_all[-1].strip()
            page_num_start = re.search('(\\d+)', page_num_start)
            page_num_start = page_num_start.group(1) if page_num_start else ''
            if len(text_all[0]) > 2 and page_num_start:
                info_dic = {
                    'question': q, 'page_num_start': page_num_start
                }
                questions.append(info_dic)

    return questions


def get_images(page_obj, pdf_path):
    """
    获取本页中的图片
    参考：https://blog.csdn.net/kmesky/article/details/103187833
    """
    image_list = []
    imgs = page_obj.images
    pdf_name = pdf_path.split('/')[-1].replace('.pdf', '')
    main_path = 'E:/temp/imgs/%s' % pdf_name
    for img in imgs:
        try:
            name = img.get('name', 'abc')
            new_img_path = '%s_%s' % (main_path, name)
            ism = img.get('stream')
            color_space = ism.__dict__.get('attrs').get('ColorSpace')
            if color_space.name == 'DeviceRGB':
                mode = "RGB"
            else:
                mode = "P"
            img_row_data = ism.get_data()

            img_filter = ism.__dict__.get('attrs').get('Filter')
            img_filter_name = img_filter.name
            if img_filter_name == 'FlateDecode':
                width, height = ism.__dict__.get('attrs').get('Width'), ism.__dict__.get('attrs').get('Height')
                if not width or not height:
                    continue
                new_img_path = new_img_path+'.png'
                size = (width, height)
                new_img = Image.frombytes(mode, size, img_row_data)
                new_img.save(new_img_path)
            elif img_filter_name == 'DCTDecode':
                new_img_path = new_img_path+'.jpg'
                new_img = open(new_img_path, 'wb')
                new_img.write(img_row_data)
                new_img.close()
            elif img_filter_name == 'JPXDecode':
                new_img_path = new_img_path+'.jp2'
                new_img = open(new_img_path, 'wb')
                new_img.write(img_row_data)
                new_img.close()
            elif img_filter_name == 'CCITTFaxDecode':
                new_img_path = new_img_path+'.tiff'
                new_img = open(new_img_path, 'wb')
                new_img.write(img_row_data)
                new_img.close()
            else:
                logging.error('wrong img_filter_name: %s' % img_filter_name)
                continue

            image_list.append(
                {'name': name, 'path': new_img_path}
            )
        except Exception as e:
            logging.error('get_images failed, pdf_path: %s, error: %s' % (pdf_path, e))
    return image_list


def get_imgs(page, path):
    new_pdf_images = []
    images = get_images(page, path)
    new_texts = ''
    for img_dic in images:
        img_path = img_dic.get('path')
        new_pdf_images.append(img_path)
        new_texts += '\n%s' % img_path
    return new_pdf_images, new_texts


def get_question_list(pdf_pages):
    """
    获取问题列表
    """
    # 目录所在页码
    catalogue_page_num = 0
    # 问题列表
    question_list = []
    stop = False
    page_max = len(pdf_pages)
    for num, page in enumerate(pdf_pages, start=1):
        if stop:
            logging.info('has found all questions, catalogue page num: %s' % (num-2))
            break
        texts = page.extract_text()
        # 目录页面可能是个图片，所以无法获取目录内容
        if not texts:
            continue
        texts = texts.strip()
        if '目' in texts and '录' in texts and not catalogue_page_num:
            new_texts = re.sub('\\s+', ' ', texts)
            if '目 录' in new_texts or '目录' in new_texts:
                catalogue_page_num = num
                question_list.extend(find_questions(texts))
        # 目录存在多页的情况
        if catalogue_page_num and num > catalogue_page_num:
            if '.......' in texts:
                logging.info('more questions page, num: %s' % num)
                question_list.extend(find_questions(texts))
            else:
                stop = True
    return question_list, page_max, catalogue_page_num


def get_answer(pdf_pages, path, question_dic, next_question):
    """
    获取问题答案
    """
    page_num_start = int(question_dic['page_num_start'])
    page_num_end = int(question_dic['page_num_end'])
    question = question_dic['question'].replace(' ', '')
    next_question = next_question.replace(' ', '')

    answer = ''
    # 记录在问题起始几页未找到问题的次数
    not_find_times = 0
    # 收集图片
    pdf_images = []

    logging.info('for question: %s, page_num_start: %s, page_num_end: %s' % (question, page_num_start, page_num_end))
    # print(page_num_start, page_num_end)

    page_max = len(pdf_pages)
    for num, page in enumerate(pdf_pages, start=1):
        # 小于问题页码不采集
        if num < page_num_start:
            continue
        # 大于问题页码不采集
        if num > page_num_end:
            break

        # 抽取文本
        texts = page.extract_text()

        # 当本页没有文本的时候 抽取图片
        if not texts:
            texts = ''
            new_pdf_images, new_texts = get_imgs(page, path)
            pdf_images.extend(new_pdf_images)
            texts += new_texts
            answer += texts + '\n'
            continue

        # 过滤掉页码
        texts_list = texts.split('\n')
        for page_info in texts_list[-2:]:
            if re.match('(\\d+)', page_info.strip()):
                texts = texts.replace(page_info, '')

        # 部分pdf提供的目录页数有错误，如果问题在前两页找不到，则不采集该问题答案
        if num == page_num_start:
            if question not in texts.replace(' ', ''):
                # 如果在起始页未找到，则page_num_start+1
                if not_find_times == 0:
                    not_find_times += 1
                    page_num_start += 1
                    continue
                else:
                    logging.error('not found question error, question_dic: %s' % json.dumps(question_dic))
                    break

            # 如果问题出现在起始页的下一页，则page_num_end+1
            if not_find_times == 1:
                page_num_end = page_num_end + 1
            if page_num_end > page_max:
                page_num_end = page_max

            # 找到本问题之后的文本
            new_texts = []
            texts_all = texts.split('\n')
            txt_num = 0
            same_row_answer = ''
            for tn, txt in enumerate(texts_all):
                if not txt:
                    continue
                txt = txt.replace(' ', '')
                if question in txt:
                    txt_num = tn
                    # 问题与回复同行的情况
                    if len(txt.strip()) > len(question.strip()):
                        same_row_answer = txt.replace(question, '').strip('。').strip('，').strip()
                    break
            if same_row_answer:
                new_texts.append(same_row_answer)
            for txt in texts_all[txt_num+1:]:
                new_texts.append(txt)
            texts = '\n'.join(new_texts)

        # 过滤掉下一个问题相关信息
        # 如果一个问题只有一页回复，则下面的处理会将问题的回复内容置为空
        if num == page_num_end and next_question:
            new_texts = []
            texts_all = texts.split('\n')
            txt_num = 0
            same_row_answer = ''
            for tn, txt in enumerate(texts_all):
                if not txt:
                    continue
                txt = txt.replace(' ', '')
                if next_question in txt:
                    txt_num = tn
                    # 问题与回复同行的情况
                    if len(txt.strip()) > len(question.strip()):
                        same_row_answer = txt.replace(question, '').strip('。').strip('，').strip()
                    break
            if same_row_answer:
                new_texts.append(same_row_answer)
            for txt in texts_all[:txt_num]:
                new_texts.append(txt)
            texts = '\n'.join(new_texts)

        # 如果是最后一个问题，最后几页实际上是盖章页，无用
        if not next_question:
            if '此页无正文' in texts or '本页无正文' in texts:
                logging.info('this is useless page: %s' % num)
                break

        texts = texts.strip()

        # 找到本页中的图片下载并记录位置
        new_pdf_images, new_texts = get_imgs(page, path)
        pdf_images.extend(new_pdf_images)
        texts += new_texts
        answer += texts + '\n'

    answer = answer.strip()
    return answer, pdf_images


def parse(pdf_pages, path=None):
    # 获取问题列表、最大页数及目录所在页码
    # 目标pdf是带有目录的文件
    get_answer_flag = False
    question_list, page_max, catalogue_page_num = get_question_list(pdf_pages)
    if not question_list:
        logging.error('no question_list, path: %s' % path)
        return get_answer_flag

    for index, question in enumerate(question_list):

        question_dic = question
        # 是否为最后一个问题
        if index == len(question_list)-1:
            next_question = ''
        else:
            next_question = question_list[index+1]['question']

        # 获取答案和图片
        answer, pdf_images = get_answer(pdf_pages, path, question_dic, next_question)

        if not answer:
            logging.error('no answer, path: %s' % path)
            continue
        else:
            get_answer_flag = True

    return get_answer_flag


def start(file_path):
    try:
        with pdfplumber.open(file_path) as pdf_obj:
            pdf_pages = pdf_obj.pages
            parse_flag = parse(pdf_pages)
    except Exception as e:
        logging.error('file_path: %s, error: %s' % (file_path, traceback.format_exc()))
        # 需要PDF解密，有的pdf有空字符串做了加密，需要对其解密
        if 'Unsupported revision' in traceback.format_exc():
            # 解密后的路径
            decrypt_path = ''
            decrypt_pdf(file_path, decrypt_path)
            try:
                with pdfplumber.open(decrypt_path) as pdf_obj:
                    pdf_pages = pdf_obj.pages
                    parse_flag = parse(pdf_pages)
            except Exception as e:
                logging.error('file_path: %s, error: %s' % (file_path, traceback.format_exc()))
                parse_flag = False
            try:
                os.remove(decrypt_path)
            except:
                pass
        else:
            parse_flag = False
    if not parse_flag:
        logging.error('parse pdf failed')


def main():
    # pdf路径
    file_path = ''
    start(file_path)


if __name__ == "__main__":
    main()
