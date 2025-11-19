import subprocess
import re
import sys
import os
import argparse
from datetime import datetime
from collections import defaultdict

# 输出级别常量
VERBOSE_QUIET = 0    # 只输出必要信息
VERBOSE_NORMAL = 1   # 正常输出（默认）
VERBOSE_DETAIL = 2   # 详细信息
VERBOSE_DEBUG = 3    # 调试信息

# 全局变量，默认为1
verbose_level = VERBOSE_NORMAL

def log_quiet(message):
    if verbose_level >= VERBOSE_QUIET:
        print(message, file=sys.stderr)

def log_normal(message):
    if verbose_level >= VERBOSE_NORMAL:
        print(message, file=sys.stderr)

def log_detail(message):
    if verbose_level >= VERBOSE_DETAIL:
        print(message, file=sys.stderr)

def log_debug(message):
    if verbose_level >= VERBOSE_DEBUG:
        print(message, file=sys.stderr)

def run_mysqlbinlog(binlog_file, extra_args=[]):
    """
    运行mysqlbinlog命令并捕获输出
    """
    cmd = ['mysqlbinlog', '--base64-output=decode-rows', '-vv'] + extra_args + [binlog_file]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running mysqlbinlog: {e.stderr}")
        return None

def run_mysqlbinlog_robust(binlog_file, extra_args=[]):
    """
    处理编码问题的方法
    """
    cmd = ['mysqlbinlog', '--base64-output=decode-rows', '-v'] + extra_args + [binlog_file]
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            print(f"错误: mysqlbinlog执行失败: {stderr.decode('utf-8', errors='ignore')}")
            return None
        
        content = None
        for encoding in ['utf-8', 'latin1', 'gbk', 'gb2312', 'cp1252']:
            try:
                content = stdout.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            content = stdout.decode('utf-8', errors='ignore')
            
        return content
        
    except Exception as e:
        print(f"错误: 执行mysqlbinlog失败: {e}")
        return None

def analyze_binlog(binlog_file, starttime=None, stoptime=None):
    """
    分析binlog，生成统计报告，支持DML事件
    """
    extra_args = []
    if starttime:
        extra_args.append('--start-datetime={}'.format(starttime))
    if stoptime:
        extra_args.append('--stop-datetime={}'.format(stoptime))
    output = run_mysqlbinlog(binlog_file, extra_args)
    if output is None:
        sys.exit(1)
    lines = output.splitlines()

    stats = defaultdict(lambda: {'inserts': 0, 'updates': 0, 'deletes': 0, 'starttime': None, 'stoptime': None, 'startpos': float('inf'), 'stoppos': 0})
    current_db = ''
    current_table = ''
    current_pos = 0
    current_time = ''
    in_event = False
    event_type = ''
    row_count = 0
    stoppos = 0
    in_query = False
    current_sql = ''
    prev_line = ''
    key = None
    current_table_map_pos = 0

    for line in lines:
        pos_match = re.search(r'at (\d+)', line)
        if pos_match:
            if in_event:
                if key is not None:
                    stats[key][event_type] += row_count
                    stats[key]['stoppos'] = max(stats[key]['stoppos'], stoppos)
                in_event = False
            current_pos = int(pos_match.group(1))
            continue

        time_match = re.match(r'#(\d{6} \d{2}:\d{2}:\d{2})', line)
        if time_match:
            current_time = datetime.strptime('20{}'.format(time_match.group(1)), '%Y%m%d %H:%M:%S').strftime('%Y-%m-%d_%H:%M:%S')

        use_match = re.search(r'USE `(.*?)`', line, re.IGNORECASE)
        if use_match:
            current_db = use_match.group(1)

        table_map = re.search(r'Table_map: `(.*?)`\.`(.*?)`', line, re.IGNORECASE)
        if table_map:
            current_db = table_map.group(1)
            current_table = table_map.group(2)
            key = (current_db, current_table)
            current_table_map_pos = current_pos

        if 'Write_rows' in line:
            event_type = 'inserts'
            in_event = True
            row_count = 0
            end_pos_match = re.search(r'end_log_pos (\d+)', line)
            if end_pos_match:
                stoppos = int(end_pos_match.group(1))
        elif 'Update_rows' in line:
            event_type = 'updates'
            in_event = True
            row_count = 0
            end_pos_match = re.search(r'end_log_pos (\d+)', line)
            if end_pos_match:
                stoppos = int(end_pos_match.group(1))
        elif 'Delete_rows' in line:
            event_type = 'deletes'
            in_event = True
            row_count = 0
            end_pos_match = re.search(r'end_log_pos (\d+)', line)
            if end_pos_match:
                stoppos = int(end_pos_match.group(1))

        if in_event and key is not None:
            if current_time:
                if stats[key]['starttime'] is None or current_time < stats[key]['starttime']:
                    stats[key]['starttime'] = current_time
                    stats[key]['startpos'] = min(stats[key]['startpos'], current_table_map_pos)
                stats[key]['stoptime'] = max(stats[key]['stoptime'] or current_time, current_time)

            if event_type == 'inserts' and '### SET' in line:
                row_count += 1
            elif event_type in ('updates', 'deletes') and '### WHERE' in line:
                row_count += 1

        if 'Query' in line and 'thread_id' in line:
            in_query = True
            current_sql = ''
            end_pos_match = re.search(r'end_log_pos (\d+)', line)
            if end_pos_match:
                stoppos = int(end_pos_match.group(1))
        if in_query:
            if not line.startswith('#') and line.strip():
                current_sql += line.strip() + ' '
            if ';' in line:
                current_sql = current_sql.strip()
                full_match = re.search(r'(`?(\w+)`?\.`?(\w+)`?)', current_sql, re.IGNORECASE)
                if full_match:
                    db = full_match.group(2)
                    table = full_match.group(3)
                    key = (db, table)
                else:
                    table_match = re.search(r'TABLE\s+(\w+)', current_sql, re.IGNORECASE)
                    table = table_match.group(1) if table_match else 'unknown'
                    db = current_db if current_db else 'unknown'
                    key = (db, table)

                sql_upper = current_sql.upper()
                if any(kw in sql_upper for kw in ['CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME']):
                    stats[key]['updates'] += 1
                elif 'INSERT' in sql_upper:
                    stats[key]['inserts'] += 1
                elif 'UPDATE' in sql_upper:
                    stats[key]['updates'] += 1
                elif 'DELETE' in sql_upper:
                    stats[key]['deletes'] += 1

                if current_time:
                    if stats[key]['starttime'] is None or current_time < stats[key]['starttime']:
                        stats[key]['starttime'] = current_time
                        stats[key]['startpos'] = min(stats[key]['startpos'], current_pos)
                    stats[key]['stoptime'] = max(stats[key]['stoptime'] or current_time, current_time)
                stats[key]['stoppos'] = max(stats[key]['stoppos'], stoppos)

                in_query = False

        prev_line = line

    if in_event and key is not None:
        stats[key][event_type] += row_count
        stats[key]['stoppos'] = max(stats[key]['stoppos'], stoppos)

    for stat_key in list(stats.keys()):
        data = stats[stat_key]
        if data['starttime'] is None:
            del stats[stat_key]
            continue
        if data['stoptime'] is None:
            data['stoptime'] = data['starttime']
        if data['startpos'] == float('inf'):
            data['startpos'] = data['stoppos']

    binlog_name = binlog_file.split('/')[-1]
    with open('binlog_stats.txt', 'w') as f:
        header = "{0:<20} {1:<20} {2:<20} {3:<12} {4:<12} {5:<8} {6:<8} {7:<8} {8:<20} {9:<30}".format('binlog', 'starttime', 'stoptime', 'startpos', 'stoppos', 'inserts', 'updates', 'deletes', 'database', 'table')
        f.write(header + '\n')
        for (db, table), data in sorted(stats.items(), key=lambda x: x[1]['starttime'] or '9999-99-99_99:99:99'):
            if any([data['inserts'], data['updates'], data['deletes']]):
                line = "{0:<20} {1:<20} {2:<20} {3:<12} {4:<12} {5:<8} {6:<8} {7:<8} {8:<20} {9:<30}".format(binlog_name, data['starttime'], data['stoptime'], data['startpos'], data['stoppos'], data['inserts'], data['updates'], data['deletes'], db, table)
                f.write(line + '\n')
    print("Generated binlog_stats.txt")

def parse_binlog_content_enhanced(content, database_filter=None, table_filter=None, flashback_mode='deletes'):
    """
    binlog内容解析，支持DELETE和UPDATE操作
    """
    operations = []
    
    lines = content.split('\n')
    i = 0
    current_db = ''
    current_table = ''
    
    log_detail(f"开始解析binlog内容，共{len(lines)}行")
    
    while i < len(lines):
        line = lines[i].strip()
        
        table_map = re.search(r'Table_map: `([^`]+)`\.`([^`]+)`', line)
        if table_map:
            current_db = table_map.group(1)
            current_table = table_map.group(2)
            log_debug(f"找到Table_map: {current_db}.{current_table}")
        
        db_match = not database_filter or current_db == database_filter
        table_match = not table_filter or current_table == table_filter
        
        if not (db_match and table_match):
            i += 1
            continue
            
        if '### DELETE FROM' in line and current_db and current_table:
            log_debug(f"找到DELETE操作: {current_db}.{current_table}")
            operation = {
                'type': 'DELETE',
                'database': current_db,
                'table': current_table,
                'values': []
            }
            
            i += 1
            while i < len(lines) and lines[i].strip().startswith('###'):
                field_line = lines[i].strip()
                if '@' in field_line and '=' in field_line:
                    value_start = field_line.find('=') + 1
                    value = field_line[value_start:].strip()
                    if '/*' in value:
                        value = value.split('/*')[0].strip()
                    operation['values'].append(process_field_value(value))
                    log_debug(f"  DELETE字段值: {value} -> {process_field_value(value)}")
                i += 1
            
            if operation['values']:
                operations.append(operation)
            continue
                
        elif '### UPDATE' in line and current_db and current_table:
            log_debug(f"找到UPDATE操作: {current_db}.{current_table}")
            operation = {
                'type': 'UPDATE',
                'database': current_db,
                'table': current_table,
                'old_values': {},
                'new_values': {}
            }
            
            i += 1
            current_section = None
            changed_fields = []
            
            while i < len(lines) and lines[i].strip().startswith('###'):
                field_line = lines[i].strip()
                
                if field_line == '### WHERE':
                    current_section = 'WHERE'
                    i += 1
                    continue
                elif field_line == '### SET':
                    current_section = 'SET'
                    i += 1
                    continue
                
                if '@' in field_line and '=' in field_line and current_section:
                    match = re.match(r'###\s+@(\d+)=(.*)', field_line)
                    if match:
                        field_num = int(match.group(1))
                        value = match.group(2).strip()
                        if '/*' in value:
                            value = value.split('/*')[0].strip()
                        
                        processed_value = process_field_value(value)
                        
                        if current_section == 'WHERE':
                            operation['old_values'][field_num] = processed_value
                            log_debug(f"  UPDATE WHERE字段{field_num}: {value} -> {processed_value}")
                        elif current_section == 'SET':
                            operation['new_values'][field_num] = processed_value
                            log_debug(f"  UPDATE SET字段{field_num}: {value} -> {processed_value}")
                            if field_num not in changed_fields:
                                changed_fields.append(field_num)
                
                i += 1
            
            if operation['old_values'] and operation['new_values']:
                operations.append(operation)
                if changed_fields and verbose_level >= VERBOSE_DETAIL:
                    log_detail(f"  更新字段变化:")
                    for field_num in sorted(changed_fields):
                        old_val = operation['old_values'].get(field_num, 'NULL')
                        new_val = operation['new_values'].get(field_num, 'NULL')
                        if old_val != new_val:
                            old_display = old_val if len(str(old_val)) < 50 else str(old_val)[:47] + "..."
                            new_display = new_val if len(str(new_val)) < 50 else str(new_val)[:47] + "..."
                            log_detail(f"    字段{field_num}: {old_display} → {new_display}")
            continue
            
        i += 1
        
    log_detail(f"解析完成，共找到{len(operations)}个操作")
    return operations

def process_field_value(value):
    """
    处理字段值，返回适合SQL的格式
    """
    value = value.strip()
    
    if value == 'NULL':
        return 'NULL'
    elif value.startswith("'") and value.endswith("'"):
        # 处理字符串，转义单引号
        inner_value = value[1:-1].replace("'", "''")
        return f"'{inner_value}'"
    elif value.startswith('"') and value.endswith('"'):
        # 处理双引号字符串
        inner_value = value[1:-1].replace("'", "''")
        return f"'{inner_value}'"
    else:
        # 数字或其他类型
        return value

def generate_recovery_sql(operations, flashback_mode='deletes'):
    """
    生成恢复SQL - 支持DELETE和UPDATE闪回
    """
    sql_statements = []
    
    for op in operations:
        if op['type'] == 'DELETE' and flashback_mode == 'deletes':
            values_str = ', '.join(op['values'])
            insert_sql = f"INSERT INTO `{op['database']}`.`{op['table']}` VALUES ({values_str});"
            sql_statements.append(insert_sql)
            log_detail(f"生成INSERT恢复语句")
            
        elif op['type'] == 'UPDATE' and flashback_mode == 'updates':
            set_parts = []
            where_parts = []
            
            field_nums = sorted(set(op['old_values'].keys()) | set(op['new_values'].keys()))
            
            for field_num in field_nums:
                if field_num in op['old_values'] and field_num in op['new_values']:
                    set_parts.append(f"`col_{field_num}` = {op['old_values'][field_num]}")
                    where_parts.append(f"`col_{field_num}` = {op['new_values'][field_num]}")
            
            if set_parts and where_parts:
                set_clause = ", ".join(set_parts)
                where_clause = " AND ".join(where_parts)
                update_sql = f"UPDATE `{op['database']}`.`{op['table']}` SET {set_clause} WHERE {where_clause};"
                sql_statements.append(update_sql)
                #log_detail(f"生成UPDATE恢复语句")
    
    return sql_statements

def save_to_file(sql_statements, output_file, flashback_mode='deletes'):
    """
    保存SQL到文件
    """
    mode_description = {
        'deletes': 'DELETE转INSERT恢复',
        'updates': 'UPDATE反向恢复',
        'inserts': 'INSERT转DELETE恢复'
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"-- Binlog数据恢复SQL\n")
        f.write(f"-- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"-- 恢复模式: {mode_description.get(flashback_mode, flashback_mode)}\n")
        f.write(f"-- 共 {len(sql_statements)} 条SQL语句\n")
        f.write("-- 请确认SQL正确性后再执行！\n")
        f.write("-- 建议先备份数据\n\n")
        
        for sql in sql_statements:
            f.write(sql + '\n')
            
    print(f"SQL已保存到: {output_file}")

def extract_sql_enhanced(binlog_file, startpos=None, stoppos=None, flashback_mode='deletes',
                        start_datetime=None, stop_datetime=None, database=None, table=None,
                        output_file=None, direct_parse=False, verbose=VERBOSE_NORMAL):

    global verbose_level
    verbose_level = verbose
    
    extra_args = []
    
    if start_datetime:
        extra_args.extend(['--start-datetime', start_datetime])
    if stop_datetime:
        extra_args.extend(['--stop-datetime', stop_datetime])
    if startpos:
        extra_args.extend(['--start-position', str(startpos)])
    if stoppos:
        extra_args.extend(['--stop-position', str(stoppos)])
    
    log_quiet(f"提取参数: 位置={startpos}-{stoppos}, 数据库={database}, 表={table}, 模式={flashback_mode}")
    
    if direct_parse:
        log_detail(f"使用直接解析模式")
        
        try:
            temp_file = f"/tmp/binlog_content_{os.getpid()}.txt"
            
            cmd = ['mysqlbinlog', '--base64-output=decode-rows', '-v'] + extra_args + [binlog_file, '>', temp_file]
            
            subprocess.run(' '.join(cmd), shell=True, check=True)
            
            with open(temp_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            os.unlink(temp_file)
            
        except Exception as e:
            log_quiet(f"错误: 直接解析binlog失败: {e}")
            return []
    else:
        log_detail(f"使用标准解析模式")
        content = run_mysqlbinlog_robust(binlog_file, extra_args)
    
    if not content:
        log_quiet("错误: 无法获取binlog内容")
        return []
    
    operations = parse_binlog_content_enhanced(
        content, 
        database_filter=database, 
        table_filter=table, 
        flashback_mode=flashback_mode
    )
    
    operation_types = defaultdict(int)
    for op in operations:
        operation_types[op['type']] += 1
    
    log_normal(f"找到 {len(operations)} 个操作: {dict(operation_types)}")
    
    sql_statements = generate_recovery_sql(operations, flashback_mode)
    
    log_normal(f"生成 {len(sql_statements)} 条SQL语句")
    
    if output_file:
        save_to_file(sql_statements, output_file, flashback_mode)
    else:
        for sql in sql_statements:
            print(sql)
    
    return sql_statements

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python binlog_tool.py analyze binlog_file [starttime stoptime]")
        print("  python binlog_tool.py extract --binlog-file file [options]")
        print("\nEnhanced extract options:")
        print("  --start-position START_POS")
        print("  --stop-position STOP_POS") 
        print("  --start-datetime START_DATETIME")
        print("  --stop-datetime STOP_DATETIME")
        print("  --database DATABASE")
        print("  --table TABLE")
        print("  --output OUTPUT_FILE")
        print("  --direct-parse")
        print("  --flashback-mode {deletes|updates|inserts}")
        print("  --verbose, -v     输出详细程度 (可重复使用: -v, -vv, -vvv)")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "analyze":
        if len(sys.argv) < 3:
            print("需要指定binlog文件")
            sys.exit(1)
        binlog_file = sys.argv[2]
        starttime = sys.argv[3] if len(sys.argv) > 3 else None
        stoptime = sys.argv[4] if len(sys.argv) > 4 else None
        analyze_binlog(binlog_file, starttime, stoptime)

    elif cmd == "extract":
        parser = argparse.ArgumentParser(description='Binlog数据提取工具')
        parser.add_argument('--binlog-file', required=True, help='binlog文件路径')
        parser.add_argument('--database', help='数据库名过滤')
        parser.add_argument('--table', help='表名过滤')
        parser.add_argument('--start-position', type=int, help='开始位置')
        parser.add_argument('--stop-position', type=int, help='结束位置')
        parser.add_argument('--start-datetime', help='开始时间')
        parser.add_argument('--stop-datetime', help='结束时间')
        parser.add_argument('--output', '-o', help='输出文件')
        parser.add_argument('--direct-parse', action='store_true', help='直接解析模式（避免编码问题）')
        parser.add_argument('--flashback-mode', default='deletes', 
                          choices=['deletes', 'updates', 'inserts'], 
                          help='闪回模式')
        parser.add_argument('--verbose', '-v', action='count', default=1,
                          help='输出详细程度 (可重复使用: -v, -vv, -vvv)')
        
        # 解析参数（跳过前两个参数：脚本名和命令）
        args = parser.parse_args(sys.argv[2:])
        
        # 映射verbose计数到级别常量
        verbosity_map = {
            0: VERBOSE_QUIET,
            1: VERBOSE_NORMAL,
            2: VERBOSE_DETAIL,
            3: VERBOSE_DEBUG
        }
        verbose_level = verbosity_map.get(args.verbose, VERBOSE_NORMAL)
        
        extract_sql_enhanced(
            binlog_file=args.binlog_file,
            startpos=args.start_position,
            stoppos=args.stop_position,
            flashback_mode=args.flashback_mode,
            start_datetime=args.start_datetime,
            stop_datetime=args.stop_datetime,
            database=args.database,
            table=args.table,
            output_file=args.output,
            direct_parse=args.direct_parse,
            verbose=verbose_level
        )

    else:
        print("Unknown command")

